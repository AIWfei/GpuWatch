from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..alert_engine import is_sample_idle
from ..gpu_probe import GpuSample
from .common import format_mib_pair

MAX_ROWS = 5000

COLUMNS = (
    "时间",
    "来源",
    "GPU",
    "名称",
    "显存（已用 / 总量）",
    "占用",
    "利用率",
    "温度",
    "判定",
)

JUDGE_COLORS = {
    "空闲": "#2e7d32",
    "繁忙": "#455a64",
    "N/A": "#78909c",
}


class QueryHistoryTab(QWidget):
    """按时间记录每次 GPU 查询的逐卡结果。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self._summary = QLabel()
        self._summary.setStyleSheet("color: #78909c;")
        clear_btn = QPushButton("清空记录")
        top.addWidget(self._summary)
        top.addStretch(1)
        top.addWidget(clear_btn)
        layout.addLayout(top)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setWordWrap(False)
        header = self._table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for column in (0, 1, 2, 4, 5, 6, 7, 8):
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
        layout.addWidget(self._table, 1)

        clear_btn.clicked.connect(self.clear)
        self._update_summary()

    def add_snapshot(
        self,
        samples: list[GpuSample],
        monitor,
        source: str = "监控",
        at: datetime | None = None,
    ) -> None:
        now = at or datetime.now()
        stamp = now.strftime("%Y-%m-%d %H:%M:%S")
        ordered = sorted(samples, key=lambda sample: sample.index)
        if not ordered:
            return

        bar = self._table.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4

        overflow = self._table.rowCount() + len(ordered) - MAX_ROWS
        if overflow > 0:
            self._table.removeRows(0, min(overflow, self._table.rowCount()))

        self._table.setUpdatesEnabled(False)
        try:
            for sample in ordered:
                row = self._table.rowCount()
                self._table.insertRow(row)
                idle = is_sample_idle(monitor, sample) if monitor else None
                if idle is None:
                    judge = "N/A"
                elif idle:
                    judge = "空闲"
                else:
                    judge = "繁忙"
                name_item = self._item(sample.name or "N/A")
                name_item.setToolTip(f"UUID: {sample.uuid}")
                judge_item = self._item(judge)
                judge_item.setForeground(QColor(JUDGE_COLORS[judge]))
                items = (
                    self._item(stamp),
                    self._item(source),
                    self._item(str(sample.index)),
                    name_item,
                    self._item(
                        format_mib_pair(sample.mem_used_mib, sample.mem_total_mib)
                    ),
                    self._item(
                        f"{sample.used_percent:.0f}%"
                        if sample.used_percent is not None
                        else "N/A"
                    ),
                    self._item(
                        f"{sample.util_percent}%"
                        if sample.util_percent is not None
                        else "N/A"
                    ),
                    self._item(
                        f"{sample.temp_c} °C"
                        if sample.temp_c is not None
                        else "N/A"
                    ),
                    judge_item,
                )
                for column, item in enumerate(items):
                    self._table.setItem(row, column, item)
                self._table.setRowHeight(row, 26)
        finally:
            self._table.setUpdatesEnabled(True)

        if at_bottom:
            bar.setValue(bar.maximum())
        self._update_summary()

    def _item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        item.setTextAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        return item

    def clear(self) -> None:
        self._table.setRowCount(0)
        self._update_summary()

    def _update_summary(self) -> None:
        self._summary.setText(
            f"已记录 {self._table.rowCount()} 条逐卡结果"
            f"（最多保留最近 {MAX_ROWS} 条）"
        )
