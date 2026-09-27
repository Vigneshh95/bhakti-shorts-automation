"""Telling you when something needs your attention, using only built-in Windows PowerShell.

- notify(): a small desktop notification (toast). Easy to miss, so it's for information only.
- ask(): a popup window that stays until answered. "Yes" runs the given command (e.g. the
  YouTube approval + upload). It opens in its own process, so a scheduled run never waits on it.
Best effort: if either is unavailable, the message is still in the run log."""
from __future__ import annotations

import os
import subprocess
import sys

from shorts.log import log

_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $x.GetElementsByTagName('text')
$t.Item(0).AppendChild($x.CreateTextNode($env:NOTE_TITLE)) > $null
$t.Item(1).AppendChild($x.CreateTextNode($env:NOTE_BODY)) > $null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))
"""

_POPUP = r"""
Add-Type -AssemblyName PresentationFramework
$buttons = if ($env:NOTE_CMD) { 'YesNo' } else { 'OK' }
$r = [System.Windows.MessageBox]::Show($env:NOTE_BODY, $env:NOTE_TITLE, $buttons, 'Information')
if ($r -eq 'Yes' -and $env:NOTE_CMD) { Start-Process -FilePath $env:NOTE_CMD -WorkingDirectory $env:NOTE_DIR }
"""


def _env(title: str, body: str, cmd: str = "", workdir: str = "") -> dict:
    # passed via environment variables: no quoting problems with Tamil text or paths
    return {**os.environ, "NOTE_TITLE": title, "NOTE_BODY": body, "NOTE_CMD": cmd, "NOTE_DIR": workdir}


def notify(title: str, body: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _TOAST],
                             env=_env(title, body), capture_output=True, text=True, timeout=30)
        return res.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as e:
        log.debug("notification failed: %s", e)
        return False


def ask(title: str, body: str, yes_command: str = "", workdir: str = "") -> bool:
    """Shows a popup that stays until answered; with yes_command the buttons are Yes/No and Yes
    runs it. Returns immediately (the popup lives in its own process)."""
    if sys.platform != "win32":
        return False
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", _POPUP],
                         env=_env(title, body, yes_command, workdir),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except OSError as e:
        log.debug("popup failed: %s", e)
        return False
