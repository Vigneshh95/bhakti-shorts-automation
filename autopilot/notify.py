"""Windows desktop notification (toast), using only built-in Windows PowerShell -- no extra
modules. Best effort: if notifications are unavailable, the message is still in the log."""
from __future__ import annotations

import os
import subprocess
import sys

from shorts.log import log

_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $x.GetElementsByTagName('text')
$t.Item(0).AppendChild($x.CreateTextNode($env:TOAST_TITLE)) > $null
$t.Item(1).AppendChild($x.CreateTextNode($env:TOAST_BODY)) > $null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))
"""


def notify(title: str, body: str) -> bool:
    if sys.platform != "win32":
        return False
    env = {**os.environ, "TOAST_TITLE": title, "TOAST_BODY": body}  # passed via env: no quoting issues
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS],
                             env=env, capture_output=True, text=True, timeout=30)
        return res.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as e:
        log.debug("notification failed: %s", e)
        return False
