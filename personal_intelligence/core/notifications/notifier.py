"""
Native Desktop Notification Provider for Personal Intelligence.
Supports Windows native Toast notifications via PowerShell / WinRT without external heavy dependencies.
"""

from datetime import datetime, timezone
import logging
import os
import platform
import re
import subprocess
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class DesktopNotifier:
    """
    Lightweight, non-blocking native desktop notification provider.
    Dispatches notifications asynchronously to prevent blocking the cognitive loop.
    """

    def __init__(self, app_name: str = "Personal Intelligence") -> None:
        self.app_name = app_name
        self.os_type = platform.system().lower()

    def send(
        self,
        title: str,
        message: str,
        priority: str = "high",
        timeout_seconds: int = 7,
    ) -> bool:
        """
        Sends a native desktop notification asynchronously.
        """
        # Run in separate daemon thread to ensure zero blocking on the main server thread
        t = threading.Thread(
            target=self._send_sync,
            args=(title, message, priority, timeout_seconds),
            daemon=True,
            name="DesktopNotificationWorker",
        )
        t.start()
        return True

    def _send_sync(
        self,
        title: str,
        message: str,
        priority: str = "high",
        timeout_seconds: int = 7,
    ) -> bool:
        """Executes platform-specific native notification dispatch."""
        clean_title = re.sub(r"[\r\n\t]+", " ", str(title)).replace('"', "'").replace("`", "").strip()[:80]
        clean_msg = re.sub(r"[\r\n\t]+", " ", str(message)).replace('"', "'").replace("`", "").strip()[:140]

        # Add priority icon
        prefix = "🚨 " if priority.lower() in ("critical", "high") else "🔔 "
        display_title = f"{prefix}{clean_title}"

        if "windows" in self.os_type:
            return self._send_windows(display_title, clean_msg, timeout_seconds)
        elif "darwin" in self.os_type:
            return self._send_macos(display_title, clean_msg)
        else:
            return self._send_linux(display_title, clean_msg)

    def _send_windows(self, title: str, message: str, timeout_seconds: int = 7) -> bool:
        """Sends Windows Toast or Balloon notification via PowerShell."""
        ps_script = f"""
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

        $template = @"
        <toast duration="short">
            <visual>
                <binding template="ToastGeneric">
                    <text>{title}</text>
                    <text>{message}</text>
                </binding>
            </visual>
        </toast>
"@

        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml($template)
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{self.app_name}").Show($toast)
        """
        try:
            # Try Modern WinRT Toast first
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if proc.returncode == 0:
                logger.info("Desktop notification sent: %s", title)
                return True
        except Exception as ex:
            logger.debug("WinRT Toast fallback note: %s", ex)

        # Fallback to NotifyIcon balloon tip
        try:
            balloon_script = f"""
            Add-Type -AssemblyName System.Windows.Forms
            $notify = New-Object System.Windows.Forms.NotifyIcon
            $notify.Icon = [System.Drawing.SystemIcons]::Information
            $notify.Visible = $True
            $notify.ShowBalloonTip({timeout_seconds * 1000}, "{title}", "{message}", [System.Windows.Forms.ToolTipIcon]::Info)
            Start-Sleep -Seconds 2
            $notify.Dispose()
            """
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", balloon_script],
                capture_output=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except Exception as ex2:
            logger.warning("Windows balloon notification failed: %s", ex2)
            return False

    def _send_macos(self, title: str, message: str) -> bool:
        """Sends macOS native UserNotification via osascript."""
        try:
            script = f'display notification "{message}" with title "{title}" sound name "default"'
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
            return True
        except Exception as ex:
            logger.debug("macOS notification failed: %s", ex)
            return False

    def _send_linux(self, title: str, message: str) -> bool:
        """Sends Linux notification via notify-send."""
        try:
            subprocess.run(["notify-send", title, message], capture_output=True, timeout=5)
            return True
        except Exception as ex:
            logger.debug("Linux notification failed: %s", ex)
            return False


# Global singleton instance
_default_notifier = DesktopNotifier()


def send_desktop_alert(title: str, message: str, priority: str = "high") -> bool:
    """Convenience function to send a high-signal desktop alert."""
    return _default_notifier.send(title=title, message=message, priority=priority)
