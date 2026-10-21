from __future__ import annotations

import math
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..alert_engine import format_rule_preview, is_sample_idle
from ..config import AppConfig
from ..gpu_probe import GpuSample
from .common import format_mib_pair

STATUS_COLORS = {
    "connected": "#2e7d32",
    "connecting": "#f9a825",
    "reconnecting": "#f9a825",
    "probe_error": "#ef6c00",
    "paused": "#757575",
    "stopped": "#757575",
    "auth_failed": "#c62828",
    "host_key_changed": "#c62828",
    "host_key_unknown": "#c62828",
    "secret_error": "#c62828",
    "error": "#c62828",
}

BANNER_ERROR = ("#ffebee", "#ef9a9a", "#b71c1c")
BANNER_WARNING = ("#fff8e1", "#ffe082", "#795548")


class StatusTab(QWidget):
    refresh_requested = Signal()
    toggle_monitoring_requested = Signal()
    snooze_requested = Signal(int)
    edit_connection_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._monitor = None
        self._samples: list[GpuSample] = []
        self._last_snapshot_at: float | None = None
        self._poll_interval = 10
        self._monitor_state = "stopped"
        self._last_code = "stopped"
        self._build_ui()
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._update_countdown)
        self._countdown_timer.start()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self._server_label = QLabel("未配置服务器")
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        self._server_label.setFont(font)
        self._dot = QLabel("●")
        self._dot.setFixedWidth(18)
        self._dot.setStyleSheet("color: #757575; font-size: 17px;")
        self._status_text = QLabel("监控未启动")
        status_font = QFont()
        status_font.setBold(True)
        self._status_text.setFont(status_font)
        top.addWidget(self._server_label)
        top.addStretch(1)
        top.addWidget(self._dot)
        top.addWidget(self._status_text)
        layout.addLayout(top)

        info = QHBoxLayout()
        self._last_update = QLabel("最后更新：—")
        self._next_poll = QLabel("下次采样：—")
        self._last_update.setStyleSheet("color: #546e7a;")
        self._next_poll.setStyleSheet("color: #546e7a;")
        self._refresh_btn = QPushButton("立即刷新")
        self._toggle_btn = QPushButton("启动监控")
        self._snooze_btn = QPushButton("稍后提醒")
        self._snooze_btn.setMenu(self._build_snooze_menu())
        info.addWidget(self._last_update)
        info.addSpacing(16)
        info.addWidget(self._next_poll)
        info.addStretch(1)
        info.addWidget(self._refresh_btn)
        info.addWidget(self._toggle_btn)
        info.addWidget(self._snooze_btn)
        layout.addLayout(info)

        self._banner = QFrame()
        self._banner.setObjectName("statusBanner")
        banner_layout = QHBoxLayout(self._banner)
        banner_layout.setContentsMargins(10, 8, 10, 8)
        self._banner_label = QLabel()
        self._banner_label.setWordWrap(True)
        self._banner_button = QPushButton("去修改连接设置")
        self._banner_button.setFlat(True)
        banner_layout.addWidget(self._banner_label, 1)
        banner_layout.addWidget(self._banner_button, 0)
        self._banner.hide()
        layout.addWidget(self._banner)

        self._stack = QStackedWidget()
        self._placeholder = QLabel("尚未获取 GPU 数据，连接成功后会自动刷新。")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #78909c; padding: 40px;")
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["GPU", "名称", "显存（已用 / 总量）", "占用", "利用率", "温度", "状态"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.setWordWrap(False)
        header = self._table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, 7):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setStyleSheet(
            """
            QTableWidget { border: 1px solid #cfd8dc; background: #ffffff;
                           alternate-background-color: #fafafa; }
            QHeaderView::section { background: #eceff1; padding: 6px;
                                   border: none; border-bottom: 1px solid #cfd8dc;
                                   font-weight: 600; color: #37474f; }
            QTableWidget::item { padding: 4px; }
            """
        )
        self._stack.addWidget(self._placeholder)
        self._stack.addWidget(self._table)
        layout.addWidget(self._stack, 1)

        self._rule_label = QLabel()
        self._rule_label.setWordWrap(True)
        self._rule_label.setStyleSheet("color: #455a64; padding: 2px 0;")
        layout.addWidget(self._rule_label)

        self._refresh_btn.clicked.connect(lambda: self.refresh_requested.emit())
        self._toggle_btn.clicked.connect(
            lambda: self.toggle_monitoring_requested.emit()
        )
        self._banner_button.clicked.connect(
            lambda: self.edit_connection_requested.emit()
        )

    def _build_snooze_menu(self) -> QMenu:
        menu = QMenu(self)
        for label, minutes in (("30 分钟", 30), ("1 小时", 60), ("2 小时", 120)):
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, m=minutes: self.snooze_requested.emit(m)
            )
        menu.addSeparator()
        cancel = menu.addAction("取消稍后提醒")
        cancel.triggered.connect(lambda: self.snooze_requested.emit(0))
        return menu

    def set_config(self, cfg: AppConfig) -> None:
        self._monitor = cfg.monitor
        self._poll_interval = cfg.monitor.poll_interval_s
        server = cfg.server
        if server.host:
            self._server_label.setText(
                f"{server.name or 'GPU 服务器'}　{server.username}@{server.host}:{server.port}"
            )
        else:
            self._server_label.setText("未配置服务器")
        self._rule_label.setText("当前规则：" + format_rule_preview(cfg.monitor))
        if self._samples:
            self._render_samples(self._samples)
        self._update_countdown()

    def set_status(self, code: str, text: str) -> None:
        self._last_code = code
        color = STATUS_COLORS.get(code, "#757575")
        self._dot.setStyleSheet(f"color: {color}; font-size: 17px;")
        self._status_text.setText(text)

        if code in (
            "auth_failed",
            "host_key_changed",
            "host_key_unknown",
            "secret_error",
            "error",
        ):
            self._show_banner(text, BANNER_ERROR)
        elif code in ("reconnecting", "probe_error"):
            self._show_banner(text, BANNER_WARNING)
        else:
            self._banner.hide()
        self._update_countdown()

    def set_monitoring_state(self, state: str) -> None:
        self._monitor_state = state
        if state == "paused":
            self._toggle_btn.setText("恢复监控")
        elif state == "running":
            self._toggle_btn.setText("暂停监控")
        else:
            self._toggle_btn.setText("启动监控")
        self._snooze_btn.setEnabled(state == "running")
        self._update_countdown()

    def set_paused(self, paused: bool) -> None:
        self.set_monitoring_state("paused" if paused else "running")

    def on_snapshot(self, samples: list[GpuSample]) -> None:
        self._samples = sorted(samples, key=lambda sample: sample.index)
        self._last_snapshot_at = time.monotonic()
        self._last_update.setText(
            "最后更新：" + datetime.now().strftime("%H:%M:%S")
        )
        self._render_samples(self._samples)
        self._stack.setCurrentWidget(self._table)
        self._update_countdown()

    def _render_samples(self, samples: list[GpuSample]) -> None:
        self._table.setUpdatesEnabled(False)
        try:
            self._table.setRowCount(0)
            self._table.setRowCount(len(samples))
            for row, sample in enumerate(samples):
                idle = (
                    is_sample_idle(self._monitor, sample) if self._monitor else None
                )
                background = QColor("#e8f5e9") if idle else None

                index_item = self._item(str(sample.index), background)
                name_item = self._item(sample.name or "N/A", background)
                name_item.setToolTip(f"UUID: {sample.uuid}")
                mem_item = self._item(
                    format_mib_pair(sample.mem_used_mib, sample.mem_total_mib),
                    background,
                )
                util_item = self._item(
                    f"{sample.util_percent}%" if sample.util_percent is not None else "N/A",
                    background,
                )
                temp_item = self._item(
                    f"{sample.temp_c} °C" if sample.temp_c is not None else "N/A",
                    background,
                )
                if idle is None:
                    state_text, state_color = "N/A", "#78909c"
                elif idle:
                    state_text, state_color = "空闲", "#2e7d32"
                else:
                    state_text, state_color = "忙碌", "#455a64"
                state_item = self._item(state_text, background)
                state_item.setForeground(QBrush(QColor(state_color)))
                bold = QFont()
                bold.setBold(True)
                state_item.setFont(bold)

                for column, item in (
                    (0, index_item),
                    (1, name_item),
                    (2, mem_item),
                    (4, util_item),
                    (5, temp_item),
                    (6, state_item),
                ):
                    self._table.setItem(row, column, item)
                self._table.setCellWidget(
                    row, 3, self._usage_widget(sample, idle, background)
                )
                self._table.setRowHeight(row, 36)
        finally:
            self._table.setUpdatesEnabled(True)

    def _item(self, text: str, background: QColor | None) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setTextAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        if background is not None:
            item.setBackground(QBrush(background))
        return item

    def _usage_widget(
        self, sample: GpuSample, idle: bool | None, background: QColor | None
    ) -> QWidget:
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(6, 5, 6, 5)
        bar = QProgressBar()
        bar.setMaximumHeight(18)
        percent = sample.used_percent
        bar.setRange(0, 100)
        if percent is None:
            bar.setValue(0)
            bar.setFormat("N/A")
        else:
            bar.setValue(max(0, min(100, round(percent))))
            bar.setFormat(f"{percent:.0f}%")
        if percent is not None and percent >= 85:
            chunk = "#ef5350"
        elif idle:
            chunk = "#66bb6a"
        else:
            chunk = "#42a5f5"
        bar.setStyleSheet(
            f"""
            QProgressBar {{ border: 1px solid #cfd8dc; border-radius: 4px;
                            background: #eceff1; text-align: center;
                            color: #263238; font-size: 11px; }}
            QProgressBar::chunk {{ background: {chunk}; border-radius: 3px; }}
            """
        )
        layout.addWidget(bar)
        if background is not None:
            box.setStyleSheet(f"background-color: {background.name()};")
        return box

    def _show_banner(self, text: str, colors: tuple[str, str, str]) -> None:
        background, border, foreground = colors
        self._banner.setStyleSheet(
            f"QFrame#statusBanner {{ background: {background};"
            f" border: 1px solid {border}; border-radius: 4px; }}"
        )
        self._banner_label.setStyleSheet(f"color: {foreground};")
        if self._last_code == "host_key_changed":
            text += "　请清除已信任指纹后重新连接。"
        elif self._last_code == "host_key_unknown":
            text += "　请在指纹确认窗口中继续，或重新测试连接。"
        elif self._last_code == "auth_failed":
            text += "　请检查连接设置后重新启动监控。"
        self._banner_label.setText(text)
        self._banner.show()

    def _update_countdown(self) -> None:
        if self._monitor_state != "running":
            self._next_poll.setText("下次采样：—")
            return
        if self._last_snapshot_at is None:
            if self._last_code in ("connected", "probe_error", "error"):
                self._next_poll.setText("下次采样：等待首次采样…")
            else:
                self._next_poll.setText("下次采样：—")
            return
        elapsed = time.monotonic() - self._last_snapshot_at
        remaining = self._poll_interval - elapsed
        if remaining > 0:
            self._next_poll.setText(f"下次采样：约 {math.ceil(remaining)} 秒")
        else:
            self._next_poll.setText("下次采样：等待中…")
