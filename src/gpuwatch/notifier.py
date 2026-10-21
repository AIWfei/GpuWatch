from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from .alert_engine import AlertEvent, Kind

log = logging.getLogger(__name__)

if sys.platform == "win32":
    import winsound

_ICONS = {
    Kind.DISCONNECT: QSystemTrayIcon.MessageIcon.Warning,
    Kind.ERROR: QSystemTrayIcon.MessageIcon.Critical,
}


class Notifier:
    def __init__(self, tray: QSystemTrayIcon, get_cfg, main_window):
        self.tray = tray
        self.get_cfg = get_cfg
        self.window = main_window

    def show(self, event: AlertEvent, force: bool = False) -> None:
        cfg = self.get_cfg()
        if not cfg.enabled and not force:
            return
        if not self.tray.isVisible():
            log.warning("tray icon not visible; notification suppressed")
        icon = _ICONS.get(event.kind, QSystemTrayIcon.MessageIcon.Information)
        self.tray.showMessage(
            event.title[:63],
            (event.message or " ")[:255],
            icon,
            cfg.duration_s * 1000,
        )
        if cfg.sound:
            self._beep()
        if event.kind in (Kind.IDLE, Kind.REMIND):
            QApplication.alert(self.window, 0)

    def _beep(self) -> None:
        if sys.platform == "win32":
            try:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except RuntimeError:
                log.debug("MessageBeep failed")
        else:
            QApplication.beep()
