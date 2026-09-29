"""Finds the 68 face landmarks (jaw, eyes, nose, lips) in one picture and prints them as JSON.
Runs in SadTalker's Python environment with its own face detector + alignment model (already
on disk in SadTalker/gfpgan/weights), from the SadTalker folder:

    .sadtalker_env\\Scripts\\python.exe <this file> picture.png
"""
import json
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, ".")  # the SadTalker folder
from src.face3d.extract_kp_videos_safe import KeypointExtractor  # noqa: E402

image = Image.open(sys.argv[1]).convert("RGB")
points = KeypointExtractor(device="cpu").extract_keypoint(image)
if float(np.mean(points)) == -1:
    print(json.dumps({"found": False}))
else:
    print(json.dumps({"found": True, "points": np.asarray(points).reshape(-1, 2).round(2).tolist()}))
