from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..logging_setup import get_log_bridge
from ..system import open_folder


class LogTab(QWidget):
    def __init__(self, log_path: Path, parent=None):
        super().__init__(parent)
        self._log_path = log_path
        self._build_ui()
        self._load_tail(log_path)
        bridge = get_log_bridge()
        if bridge is not None:
            bridge.record.connect(self._append)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        hint = QLabel("最多显示最近 2000 行日志。")
        hint.setStyleSheet("color: #78909c;")
        open_btn = QPushButton("打开日志目录")
        clear_btn = QPushButton("清空")
        export_btn = QPushButton("导出")
        top.addWidget(hint)
        top.addStretch(1)
        top.addWidget(open_btn)
        top.addWidget(clear_btn)
        top.addWidget(export_btn)
        layout.addLayout(top)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(2000)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Consolas", 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._view.setFont(font)
        self._view.setStyleSheet(
            "QPlainTextEdit { background: #ffffff; border: 1px solid #cfd8dc; }"
        )
        layout.addWidget(self._view, 1)

        open_btn.clicked.connect(self._open_log_dir)
        clear_btn.clicked.connect(self._view.clear)
        export_btn.clicked.connect(self._export)

    def _load_tail(self, log_path: Path) -> None:
        try:
            size = log_path.stat().st_size
            with log_path.open("rb") as handle:
                handle.seek(max(0, size - 128_000))
                data = handle.read()
        except OSError:
            return
        lines = data.decode("utf-8", "replace").splitlines()[-2000:]
        if lines:
            self._view.setPlainText("\n".join(lines))
            self._view.moveCursor(QTextCursor.MoveOperation.End)
            bar = self._view.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _append(self, text: str) -> None:
        bar = self._view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        self._view.appendPlainText(text)
        if at_bottom:
            bar.setValue(bar.maximum())

    def _open_log_dir(self) -> None:
        try:
            open_folder(self._log_path.parent)
        except OSError as exc:
            QMessageBox.warning(self, "无法打开目录", str(exc))

    def _export(self) -> None:
        default_name = f"gpuwatch-log-{datetime.now():%Y%m%d-%H%M%S}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出日志",
            str(Path.home() / default_name),
            "文本文件 (*.txt);;所有文件 (*)",
        )
        if not path:
            return
        try:
            Path(path).write_text(self._view.toPlainText(), "utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出完成", f"日志已导出到：\n{path}")
