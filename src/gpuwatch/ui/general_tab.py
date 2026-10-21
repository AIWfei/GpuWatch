from __future__ import annotations

from PySide6.QtCore import QTime, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ..config import LOG_LEVELS, GeneralCfg, NotifyCfg
from ..system import autostart_supported
from .common import clear_invalid, mark_invalid


class GeneralTab(QWidget):
    changed = Signal()
    test_notification_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._invalid_widgets: list[QWidget] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        notify_group = QGroupBox("通知")
        notify_form = QFormLayout(notify_group)
        notify_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self._notify_enabled = QCheckBox("启用桌面通知")
        self._sound = QCheckBox("播放提示音")
        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(1, 120)
        self._duration_spin.setSuffix(" 秒")
        self._disconnect_check = QCheckBox("连接中断或采样失败时通知")
        self._disconnect_spin = QSpinBox()
        self._disconnect_spin.setRange(1, 100)
        self._disconnect_spin.setSuffix(" 次连续失败后")
        self._busy_again = QCheckBox("显存重新被占用时通知")
        self._quiet_check = QCheckBox("启用免打扰时段")
        self._quiet_start = QTimeEdit()
        self._quiet_start.setDisplayFormat("HH:mm")
        self._quiet_end = QTimeEdit()
        self._quiet_end.setDisplayFormat("HH:mm")
        quiet_row = QHBoxLayout()
        quiet_row.addWidget(QLabel("从"))
        quiet_row.addWidget(self._quiet_start)
        quiet_row.addWidget(QLabel("到"))
        quiet_row.addWidget(self._quiet_end)
        quiet_row.addStretch(1)

        notify_form.addRow("", self._notify_enabled)
        notify_form.addRow("", self._sound)
        notify_form.addRow("通知停留时长", self._duration_spin)
        notify_form.addRow("", self._disconnect_check)
        notify_form.addRow("断线判定", self._disconnect_spin)
        notify_form.addRow("", self._busy_again)
        notify_form.addRow("", self._quiet_check)
        notify_form.addRow("免打扰时段", quiet_row)

        test_row = QHBoxLayout()
        self._test_btn = QPushButton("发送测试通知")
        test_row.addWidget(self._test_btn)
        test_row.addStretch(1)
        notify_form.addRow("", test_row)
        notify_hint = QLabel(
            "Windows 10/11 会忽略通知停留时长，实际时长由系统“辅助功能”设置决定；"
            "专注助手开启时通知只进入操作中心。"
        )
        notify_hint.setStyleSheet("color: #78909c;")
        notify_hint.setWordWrap(True)
        notify_form.addRow("", notify_hint)
        layout.addWidget(notify_group)

        general_group = QGroupBox("启动与窗口")
        general_form = QFormLayout(general_group)
        general_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self._autostart = QCheckBox("开机自启（当前用户）")
        self._start_minimized = QCheckBox("自启时静默启动到托盘")
        self._close_to_tray = QCheckBox("点击关闭按钮时隐藏到托盘")
        self._minimize_to_tray = QCheckBox("点击最小化时隐藏到托盘")
        self._auto_monitor = QCheckBox("启动程序后自动开始监控")
        self._log_level = QComboBox()
        for level in LOG_LEVELS:
            self._log_level.addItem(level, level)
        self._autostart_available = autostart_supported()
        if not self._autostart_available:
            self._autostart.setEnabled(False)
            self._autostart.setToolTip("当前系统不支持 Windows 开机自启设置")
        general_form.addRow("", self._autostart)
        general_form.addRow("", self._start_minimized)
        general_form.addRow("", self._close_to_tray)
        general_form.addRow("", self._minimize_to_tray)
        general_form.addRow("", self._auto_monitor)
        general_form.addRow("日志级别", self._log_level)
        layout.addWidget(general_group)
        layout.addStretch(1)

        self._notify_enabled.toggled.connect(self._on_edit)
        self._sound.toggled.connect(self._on_edit)
        self._disconnect_check.toggled.connect(self._on_edit)
        self._busy_again.toggled.connect(self._on_edit)
        self._quiet_check.toggled.connect(self._quiet_toggled)
        self._quiet_start.timeChanged.connect(self._on_edit)
        self._quiet_end.timeChanged.connect(self._on_edit)
        self._autostart.toggled.connect(self._on_edit)
        self._start_minimized.toggled.connect(self._on_edit)
        self._close_to_tray.toggled.connect(self._on_edit)
        self._minimize_to_tray.toggled.connect(self._on_edit)
        self._auto_monitor.toggled.connect(self._on_edit)
        self._duration_spin.valueChanged.connect(self._on_edit)
        self._disconnect_spin.valueChanged.connect(self._on_edit)
        self._log_level.currentIndexChanged.connect(self._on_edit)
        self._test_btn.clicked.connect(
            lambda: self.test_notification_requested.emit()
        )
        self._quiet_toggled(self._quiet_check.isChecked())

    def _quiet_toggled(self, checked: bool) -> None:
        self._quiet_start.setEnabled(checked)
        self._quiet_end.setEnabled(checked)
        self._on_edit()

    def _on_edit(self, *_args) -> None:
        if self._loading:
            return
        self._clear_validation()
        self.changed.emit()

    def _clear_validation(self) -> None:
        clear_invalid(self._invalid_widgets)
        self._invalid_widgets.clear()

    def populate(self, notify: NotifyCfg, general: GeneralCfg) -> None:
        self._loading = True
        try:
            self._notify_enabled.setChecked(notify.enabled)
            self._sound.setChecked(notify.sound)
            self._duration_spin.setValue(notify.duration_s)
            self._disconnect_check.setChecked(notify.notify_on_disconnect)
            self._disconnect_spin.setValue(notify.disconnect_after_failures)
            self._busy_again.setChecked(notify.notify_on_busy_again)
            self._quiet_check.setChecked(notify.quiet_hours.enabled)
            start = QTime.fromString(notify.quiet_hours.start, "HH:mm")
            end = QTime.fromString(notify.quiet_hours.end, "HH:mm")
            self._quiet_start.setTime(start if start.isValid() else QTime(23, 0))
            self._quiet_end.setTime(end if end.isValid() else QTime(8, 0))
            self._quiet_start.setEnabled(notify.quiet_hours.enabled)
            self._quiet_end.setEnabled(notify.quiet_hours.enabled)

            self._autostart.setChecked(
                general.start_with_windows and self._autostart_available
            )
            self._start_minimized.setChecked(general.start_minimized)
            self._close_to_tray.setChecked(general.close_to_tray)
            self._minimize_to_tray.setChecked(general.minimize_to_tray)
            self._auto_monitor.setChecked(general.auto_start_monitoring)
            level_index = self._log_level.findData(general.log_level)
            self._log_level.setCurrentIndex(level_index if level_index >= 0 else 1)
            self._clear_validation()
        finally:
            self._loading = False

    def collect(self) -> tuple[NotifyCfg, GeneralCfg]:
        notify = NotifyCfg(
            enabled=self._notify_enabled.isChecked(),
            sound=self._sound.isChecked(),
            duration_s=self._duration_spin.value(),
            notify_on_busy_again=self._busy_again.isChecked(),
            notify_on_disconnect=self._disconnect_check.isChecked(),
            disconnect_after_failures=self._disconnect_spin.value(),
            quiet_hours=self._quiet_hours(),
        )
        general = GeneralCfg(
            start_with_windows=self._autostart.isChecked(),
            start_minimized=self._start_minimized.isChecked(),
            close_to_tray=self._close_to_tray.isChecked(),
            minimize_to_tray=self._minimize_to_tray.isChecked(),
            auto_start_monitoring=self._auto_monitor.isChecked(),
            log_level=self._log_level.currentData() or "INFO",
        )
        return notify, general

    def _quiet_hours(self):
        from ..config import QuietHoursCfg

        return QuietHoursCfg(
            enabled=self._quiet_check.isChecked(),
            start=self._quiet_start.time().toString("HH:mm"),
            end=self._quiet_end.time().toString("HH:mm"),
        )

    def validate(self) -> list[tuple[QWidget, str]]:
        self._clear_validation()
        errors: list[tuple[QWidget, str]] = []
        if self._quiet_check.isChecked():
            if self._quiet_start.time() == self._quiet_end.time():
                errors.append(
                    (
                        self._quiet_start,
                        "免打扰起止时间不能相同",
                    )
                )
                errors.append((self._quiet_end, "免打扰起止时间不能相同"))
        self._invalid_widgets = mark_invalid(errors)
        return errors
