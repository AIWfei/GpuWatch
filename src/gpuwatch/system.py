from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path

from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .config import APP_DIR

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "GpuWatch"
SINGLE_INSTANCE_KEY = "GpuWatch-single-instance"


def resource_path(rel: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / rel


def autostart_supported() -> bool:
    return sys.platform == "win32"


def _autostart_command(minimized: bool) -> str:
    flag = " --minimized" if minimized else ""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"{flag}'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    launcher = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{launcher}" -m gpuwatch{flag}'


def set_autostart(enabled: bool, minimized: bool = True, name: str = AUTOSTART_NAME) -> None:
    if not autostart_supported():
        raise OSError("当前系统不支持开机自启设置")
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(
                key, name, 0, winreg.REG_SZ, _autostart_command(minimized)
            )
        else:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass


def is_autostart(name: str = AUTOSTART_NAME) -> bool:
    if not autostart_supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, name)
            return True
    except FileNotFoundError:
        return False


def refresh_autostart(minimized: bool = True) -> None:
    try:
        if is_autostart():
            set_autostart(True, minimized=minimized)
    except OSError:
        log.exception("failed to refresh autostart entry")


def set_app_user_model_id(app_id: str = "GpuWatch.Desktop.1") -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        log.debug("failed to set AppUserModelID", exc_info=True)


def acquire_single_instance(on_activate) -> QLocalServer | None:
    socket = QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_KEY)
    if socket.waitForConnected(300):
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(300)
        socket.disconnectFromServer()
        return None

    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()

    def handle_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.close()
            conn.deleteLater()
        on_activate()

    server.newConnection.connect(handle_connection)
    if not server.listen(SINGLE_INSTANCE_KEY):
        log.warning("failed to listen for single-instance socket: %s", server.errorString())
    return server


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.startfile(str(path))
