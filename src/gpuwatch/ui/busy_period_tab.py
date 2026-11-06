from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
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

MAX_PERIODS = 1000

COLUMNS = ("GPU", "名称", "开始时间", "结束时间", "持续时长", "状态")

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass
class _Period:
    gpu: int
    name: str
    start: datetime
    end: datetime | None = None
    row: int = -1


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    text = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{days} 天 {text}" if days else text


class BusyPeriodTab(QWidget):
    """按 GPU 记录繁忙时段：首次查询到繁忙开始，下次查询到空闲结束。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._periods: list[_Period] = []
        self._open: dict[int, _Period] = {}
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

        hint = QLabel(
            "仅统计“规则”页中纳入监控的 GPU；每张卡首次查询到繁忙即开始计时，"
            "下一次查询到空闲时结束该时段，监控停止时也会结束进行中的时段。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #78909c;")
        layout.addWidget(hint)

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
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3, 4, 5):
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
        at: datetime | None = None,
    ) -> None:
        if monitor is None:
            return
        now = at or datetime.now()
        picked = [
            sample
            for sample in samples
            if not monitor.gpu_filter or sample.index in monitor.gpu_filter
        ]
        for sample in sorted(picked, key=lambda item: item.index):
            idle = is_sample_idle(monitor, sample)
            if idle is None:
                continue
            period = self._open.get(sample.index)
            if idle:
                if period is not None:
                    period.end = now
                    del self._open[sample.index]
                    self._populate_row(period, now)
            elif period is None:
                period = _Period(sample.index, sample.name or "N/A", now)
                self._periods.append(period)
                self._append_row(period, now)
                self._open[sample.index] = period

        for period in self._open.values():
            self._populate_row(period, now)

        if self._prune():
            self._rebuild(now)
        self._update_summary()

    def close_open(self, at: datetime | None = None) -> None:
        now = at or datetime.now()
        if not self._open:
            return
        for period in list(self._open.values()):
            period.end = now
            self._populate_row(period, now)
        self._open.clear()
        self._update_summary()

    def clear(self) -> None:
        self._periods.clear()
        self._open.clear()
        self._table.setRowCount(0)
        self._update_summary()

    def _append_row(self, period: _Period, now: datetime) -> None:
        period.row = self._table.rowCount()
        self._table.insertRow(period.row)
        self._table.setRowHeight(period.row, 26)
        self._populate_row(period, now)

    def _populate_row(self, period: _Period, now: datetime) -> None:
        if period.row < 0:
            return
        ongoing = period.end is None
        end_text = "—" if ongoing else period.end.strftime(TIME_FORMAT)
        end = period.end or now
        duration = _format_duration((end - period.start).total_seconds())
        background = QColor("#fff3e0") if ongoing else None

        cells = (
            str(period.gpu),
            period.name,
            period.start.strftime(TIME_FORMAT),
            end_text,
            duration,
            "进行中" if ongoing else "已结束",
        )
        for column, text in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            if background is not None:
                item.setBackground(QBrush(background))
            if column == 5:
                item.setForeground(
                    QColor("#ef6c00" if ongoing else "#546e7a")
                )
            self._table.setItem(period.row, column, item)

    def _prune(self) -> bool:
        dropped = False
        while len(self._periods) > MAX_PERIODS:
            closed = next(
                (period for period in self._periods if period.end is not None),
                None,
            )
            if closed is None:
                break
            self._periods.remove(closed)
            dropped = True
        return dropped

    def _rebuild(self, now: datetime) -> None:
        self._table.setRowCount(0)
        for period in self._periods:
            self._append_row(period, now)

    def _update_summary(self) -> None:
        self._summary.setText(
            f"共记录 {len(self._periods)} 个繁忙时段，"
            f"其中 {len(self._open)} 个进行中（最多保留 {MAX_PERIODS} 个）"
        )
