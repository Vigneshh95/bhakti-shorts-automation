"""Render stage: ONE ffmpeg process does everything after the frame generator --
libass text (captions, hook, outro, watermark), fades, the second loudnorm pass, hardware
encoding and muxing. Frames stream in through a pipe as compact YUV 4:2:0, so nothing is
written to disk between stages and nothing is ever re-encoded."""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path

import cv2

from shorts import ffmpeg
from shorts.effects import Effect, RenderContext
from shorts.log import log
from shorts.stages import visuals


def render(segments: list[visuals.Segment], effects: list[Effect], ass_path: Path, audio, cfg: dict,
           work: Path, out_path: Path) -> str:
    v = cfg["video"]
    W, H, fps = v["width"], v["height"], v["fps"]
    duration = audio.duration
    ff = cfg["paths"]["ffmpeg"]
    threads = int(cfg["run"]["threads"])
    cv2.setNumThreads(threads)

    ctx = RenderContext(W, H, fps, duration, cfg["effects"]["kenburns"].get("seed", 7))
    frame_effects = [e for e in effects if e.has_frame]
    for e in frame_effects:
        e.prepare(ctx)

    # libass reads the .ass + fonts through a filter string, where Windows drive letters
    # need escaping; running ffmpeg from the work folder with relative names avoids it.
    fonts = work / "fonts"
    shutil.copytree(cfg["paths"]["fonts"], fonts, dirs_exist_ok=True)

    fx = cfg["effects"]
    vf = [f"ass={ass_path.name}:fontsdir=fonts"]
    if fx["fade"]["enabled"]:
        vf += [f"fade=t=in:st=0:d={fx['fade']['in_s']}",
               f"fade=t=out:st={max(0, duration - fx['fade']['out_s']):.3f}:d={fx['fade']['out_s']}"]
    af = [audio.loudnorm_filter, f"aresample={cfg['audio']['sample_rate']}"]
    if fx["fade"]["enabled"]:
        af += [f"afade=t=out:st={max(0, duration - fx['fade']['out_s']):.3f}:d={fx['fade']['out_s']}"]

    inputs = ["-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
              "-i", audio.mix_path.name]
    video_chain = ",".join(vf)
    overlay = fx["particles"].get("overlay") if fx["particles"]["enabled"] else ""
    if overlay:
        inputs += ["-stream_loop", "-1", "-i", str(Path(overlay).resolve())]
        graph = (f"[2:v]scale={W}:{H},format=yuv420p[ov];[0:v][ov]blend=all_mode=screen:shortest=1,"
                 f"{video_chain}[v];[1:a]{','.join(af)}[a]")
    else:
        graph = f"[0:v]{video_chain}[v];[1:a]{','.join(af)}[a]"

    enc, enc_name = ffmpeg.encoder_args(ff, v["encoder"], v["quality"], threads)
    tmp_out = out_path.with_suffix(".partial.mp4")
    cmd = [str(ff), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", *inputs,
           "-filter_complex", graph, "-map", "[v]", "-map", "[a]", *enc, "-r", str(fps),
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{duration:.3f}", str(tmp_out.resolve())]
    log.info("  encoder: %s", enc_name)

    errlog = work / "ffmpeg_render.log"
    with open(errlog, "w", encoding="utf-8") as err:
        proc = subprocess.Popen(cmd, cwd=work, stdin=subprocess.PIPE, stderr=err)
        n = int(round(duration * fps))
        t0, last = time.perf_counter(), -1
        spent = {"motion": 0.0, "effects": 0.0, "convert": 0.0, "pipe": 0.0}
        try:
            frame_iter = visuals.frames(segments, W, H, fps, duration, fx["transition"])
            for i in range(n):
                a = time.perf_counter()
                t, rgb = next(frame_iter)
                b = time.perf_counter()
                for e in frame_effects:
                    e.frame(rgb, t)
                c = time.perf_counter()
                data = cv2.cvtColor(rgb, cv2.COLOR_RGB2YUV_I420).tobytes()
                d = time.perf_counter()
                proc.stdin.write(data)  # blocks while ffmpeg is busy encoding: "pipe" time = waiting on ffmpeg
                e_ = time.perf_counter()
                spent["motion"] += b - a
                spent["effects"] += c - b
                spent["convert"] += d - c
                spent["pipe"] += e_ - d
                pct = (i + 1) * 100 // n
                if pct // 10 != last // 10:
                    last = pct
                    rate = (i + 1) / max(time.perf_counter() - t0, 1e-6)
                    log.info("  rendering %3d%%  (%d/%d frames, %.0f fps)", pct, i + 1, n, rate)
        except BrokenPipeError:
            pass
        finally:
            if proc.stdin:
                proc.stdin.close()
            wait0 = time.perf_counter()
            proc.wait()
            spent["encoder flush"] = time.perf_counter() - wait0
    log.info("  render time split: %s", ", ".join(f"{k} {v:.1f}s" for k, v in spent.items()))
    if proc.returncode != 0:
        raise ffmpeg.FFmpegError(f"Render failed (exit {proc.returncode}). Details: {errlog}\n"
                                 + "\n".join(errlog.read_text(encoding="utf-8", errors="replace").splitlines()[-10:]))
    tmp_out.replace(out_path)
    return enc_name
