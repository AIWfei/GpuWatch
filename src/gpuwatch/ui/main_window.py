from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, LOG_PATH
from .connection_tab import ConnectionTab
from .general_tab import GeneralTab
from .log_tab import LogTab
from .rules_tab import RulesTab
from .status_tab import StatusTab

TAB_TITLES = ("状态", "连接", "规则", "通知与常规", "日志")
EDITABLE_TABS = (1, 2, 3)


class MainWindow(QMainWindow):
    save_requested = Signal()
    revert_requested = Signal()
    exit_requested = Signal()
    activated = Signal()
    shown = Signal()

    def __init__(
        self,
        cfg: AppConfig,
        secret_presence: Callable[[str], bool],
        tray: QSystemTrayIcon | None,
        parent=None,
    ):
        super().__init__(parent)
        self.quitting = False
        self._applying = False
        self._dirty = False
        self._tip_shown = False
        self._secret_presence = secret_presence
        self._tray = tray
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.setWindowTitle("GpuWatch – GPU 显存监控")
        self.resize(1000, 760)
        self.setMinimumSize(860, 620)
        self._build_ui()
        self._shortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        self._shortcut.activated.connect(lambda: self.save_requested.emit())
        self.apply_config(cfg)

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.tabs = QTabWidget()
        self.status_tab = StatusTab()
        self.connection_tab = ConnectionTab()
        self.rules_tab = RulesTab()
        self.general_tab = GeneralTab()
        self.log_tab = LogTab(LOG_PATH)
        self.tabs.addTab(self.status_tab, TAB_TITLES[0])
        self.tabs.addTab(self.connection_tab, TAB_TITLES[1])
        self.tabs.addTab(self.rules_tab, TAB_TITLES[2])
        self.tabs.addTab(self.general_tab, TAB_TITLES[3])
        self.tabs.addTab(self.log_tab, TAB_TITLES[4])
        layout.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        self._dirty_label = QLabel("")
        self._dirty_label.setStyleSheet("color: #ef6c00;")
        self._revert_btn = QPushButton("还原修改")
        self._save_btn = QPushButton("保存并应用")
        self._save_btn.setDefault(True)
        bottom.addWidget(self._dirty_label)
        bottom.addStretch(1)
        bottom.addWidget(self._revert_btn)
        bottom.addWidget(self._save_btn)
        layout.addLayout(bottom)
        self.setCentralWidget(central)

        self.connection_tab.changed.connect(self._mark_dirty)
        self.rules_tab.changed.connect(self._mark_dirty)
        self.general_tab.changed.connect(self._mark_dirty)
        self._save_btn.clicked.connect(lambda: self.save_requested.emit())
        self._revert_btn.clicked.connect(lambda: self.revert_requested.emit())

        self.setStyleSheet(
            """
            QLineEdit[invalid="true"], QSpinBox[invalid="true"],
            QDoubleSpinBox[invalid="true"], QComboBox[invalid="true"],
            QTimeEdit[invalid="true"] {
                border: 1px solid #d32f2f; border-radius: 3px;
            }
            QRadioButton[invalid="true"], QCheckBox[invalid="true"] {
                color: #c62828;
            }
            """
        )

    def apply_config(self, cfg: AppConfig) -> None:
        self._applying = True
        try:
            self._cfg = cfg
            self.status_tab.set_config(cfg)
            self.connection_tab.populate(
                cfg.server,
                self._secret_presence("password"),
                self._secret_presence("passphrase"),
            )
            self.rules_tab.populate(cfg.monitor)
            self.general_tab.populate(cfg.notify, cfg.general)
        finally:
            self._applying = False
        self.mark_clean()

    def set_secret_presence(self, has_password: bool, has_passphrase: bool) -> None:
        self.connection_tab.set_secret_presence(has_password, has_passphrase)

    def mark_clean(self) -> None:
        self._dirty = False
        self._update_titles()
        self._dirty_label.setText("")
        self._revert_btn.setEnabled(False)

    def _mark_dirty(self) -> None:
        if self._applying or self._dirty:
            return
        self._dirty = True
        self._update_titles()
        self._dirty_label.setText("有未保存的修改")
        self._revert_btn.setEnabled(True)

    def _update_titles(self) -> None:
        for index, title in enumerate(TAB_TITLES):
            suffix = " *" if self._dirty and index in EDITABLE_TABS else ""
            self.tabs.setTabText(index, title + suffix)
        self.setWindowTitle(
            ("* " if self._dirty else "") + "GpuWatch – GPU 显存监控"
        )

    def show_validation_errors(self, tab_index: int, messages: list[str]) -> None:
        self.tabs.setCurrentIndex(tab_index)
        self.show_and_raise()
        QMessageBox.warning(
            self,
            "设置未保存",
            "请先修正以下问题：\n\n" + "\n".join(f"• {message}" for message in messages),
        )

    def show_connection_tab(self) -> None:
        self.tabs.setCurrentIndex(1)
        self.show_and_raise()

    def show_and_raise(self) -> None:
        self.setWindowState(
            self.windowState() & ~Qt.WindowState.WindowMinimized
        )
        self.show()
        self.raise_()
        self.activateWindow()

    def show_status_message(self, text: str, timeout: int = 5000) -> None:
        self.statusBar().showMessage(text, timeout)

    def changeEvent(self, event) -> None:
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self._cfg.general.minimize_to_tray
            and self._tray_available
            and not self.quitting
        ):
            QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        if (
            self._cfg.general.close_to_tray
            and not self.quitting
            and self._tray_available
        ):
            event.ignore()
            self.hide()
            if not self._tip_shown and self._tray is not None:
                self._tip_shown = True
                self._tray.showMessage(
                    "GpuWatch 仍在后台运行",
                    "右键托盘图标可退出程序",
                    QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )
        else:
            event.accept()
            if not self.quitting:
                self.exit_requested.emit()

    def event(self, event) -> bool:
        result = super().event(event)
        if event.type() == QEvent.Type.WindowActivate:
            self.activated.emit()
        elif event.type() == QEvent.Type.Show:
            self.shown.emit()
        return result
