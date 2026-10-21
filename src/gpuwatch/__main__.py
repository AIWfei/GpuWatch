from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .app import AppController
from .config import ConfigStore, ensure_app_dir
from .logging_setup import setup_logging
from .system import acquire_single_instance, set_app_user_model_id
from .ui.icons import app_icon

log = logging.getLogger(__name__)


def _install_excepthook() -> None:
    def handle(exc_type, exc, tb) -> None:
        logging.getLogger("gpuwatch").critical(
            "uncaught exception", exc_info=(exc_type, exc, tb)
        )
        try:
            QMessageBox.critical(
                None,
                "GpuWatch 发生错误",
                f"{exc_type.__name__}: {exc}\n\n详情请查看日志文件。",
            )
        except Exception:
            pass

    sys.excepthook = handle


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("GpuWatch")
    app.setApplicationDisplayName("GpuWatch")
    app.setOrganizationName("GpuWatch")
    app.setQuitOnLastWindowClosed(False)
    set_app_user_model_id()
    app.setWindowIcon(app_icon())
    setup_logging("INFO")
    _install_excepthook()

    window_ref: list = []
    guard = acquire_single_instance(
        lambda: window_ref and window_ref[0].show_and_raise()
    )
    if guard is None:
        log.info("another GpuWatch instance is already running")
        return 0

    ensure_app_dir()
    store = ConfigStore()
    cfg = store.load()
    setup_logging(cfg.general.log_level)

    controller = AppController(app, store, cfg)
    window_ref.append(controller.window)
    controller.sync_autostart()

    first_run = not cfg.server.host.strip()
    if first_run:
        controller.mark_unconfigured()
        controller.window.tabs.setCurrentIndex(1)
        controller.window.show()
    elif "--minimized" not in sys.argv:
        controller.window.show()

    if first_run:
        log.info("first run: waiting for connection settings")
    elif cfg.general.auto_start_monitoring:
        controller.start_worker()
    else:
        log.info("automatic monitoring is disabled")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
