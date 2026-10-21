from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..alert_engine import AGGREGATE_LABELS, format_rule_preview
from ..config import MonitorCfg
from ..gpu_probe import GpuSample
from .common import clear_invalid, mark_invalid


class RulesTab(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._gpu_names: dict[int, str] = {}
        self._wanted_indices: set[int] = set()
        self._checks: dict[int, QCheckBox] = {}
        self._invalid_widgets: list[QWidget] = []
        self._build_ui()
        self._update_units()
        self._update_gpu_enabled()
        self._update_preview()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        sampling_group = QGroupBox("采样与判定")
        form = QFormLayout(sampling_group)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._poll_spin = QSpinBox()
        self._poll_spin.setRange(5, 3600)
        self._poll_spin.setSingleStep(5)
        self._poll_spin.setSuffix(" 秒")
        self._metric_combo = QComboBox()
        self._metric_combo.addItem("显存占用百分比（已用 % < 阈值）", "used_percent")
        self._metric_combo.addItem("已用显存（已用 MiB < 阈值）", "used_mib")
        self._metric_combo.addItem("空闲显存（空闲 MiB ≥ 阈值）", "free_mib")
        self._threshold_label = QLabel("阈值")
        self._threshold_spin = QDoubleSpinBox()
        self._hysteresis_label = QLabel("回差")
        self._hysteresis_spin = QDoubleSpinBox()
        self._debounce_spin = QSpinBox()
        self._debounce_spin.setRange(1, 100)
        self._debounce_spin.setSuffix(" 次")
        self._cooldown_spin = QDoubleSpinBox()
        self._cooldown_spin.setRange(0, 1440)
        self._cooldown_spin.setDecimals(1)
        self._cooldown_spin.setSingleStep(1)
        self._cooldown_spin.setSuffix(" 分钟")
        repeat_row = QHBoxLayout()
        self._repeat_check = QCheckBox("持续空闲时重复提醒")
        self._repeat_spin = QDoubleSpinBox()
        self._repeat_spin.setRange(0.5, 1440)
        self._repeat_spin.setDecimals(1)
        self._repeat_spin.setSingleStep(10)
        self._repeat_spin.setValue(30)
        self._repeat_spin.setSuffix(" 分钟")
        repeat_row.addWidget(self._repeat_check)
        repeat_row.addWidget(self._repeat_spin)
        repeat_row.addStretch(1)
        form.addRow("轮询间隔", self._poll_spin)
        form.addRow("判定口径", self._metric_combo)
        form.addRow(self._threshold_label, self._threshold_spin)
        form.addRow(self._hysteresis_label, self._hysteresis_spin)
        form.addRow("防抖次数", self._debounce_spin)
        form.addRow("冷却时间", self._cooldown_spin)
        form.addRow("重复提醒", repeat_row)
        layout.addWidget(sampling_group)

        scope_group = QGroupBox("判定方式与 GPU 范围")
        scope_layout = QVBoxLayout(scope_group)
        aggregate_row = QHBoxLayout()
        aggregate_row.addWidget(QLabel("判定方式"))
        self._aggregate_combo = QComboBox()
        for key in ("per_gpu", "any", "all"):
            self._aggregate_combo.addItem(AGGREGATE_LABELS[key], key)
        aggregate_row.addWidget(self._aggregate_combo)
        aggregate_row.addStretch(1)
        scope_layout.addLayout(aggregate_row)

        scope_radios = QHBoxLayout()
        self._all_radio = QRadioButton("全部 GPU")
        self._specific_radio = QRadioButton("仅指定 GPU")
        self._all_radio.setChecked(True)
        scope_radios.addWidget(self._all_radio)
        scope_radios.addWidget(self._specific_radio)
        scope_radios.addStretch(1)
        scope_layout.addLayout(scope_radios)

        self._gpu_hint = QLabel()
        self._gpu_hint.setStyleSheet("color: #78909c;")
        self._gpu_hint.setWordWrap(True)
        scope_layout.addWidget(self._gpu_hint)

        self._gpu_scroll = QScrollArea()
        self._gpu_scroll.setWidgetResizable(True)
        self._gpu_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._gpu_scroll.setMaximumHeight(110)
        self._gpu_container = QWidget()
        self._gpu_layout = QGridLayout(self._gpu_container)
        self._gpu_layout.setContentsMargins(0, 0, 0, 0)
        self._gpu_layout.setHorizontalSpacing(20)
        self._gpu_layout.setVerticalSpacing(6)
        self._gpu_scroll.setWidget(self._gpu_container)
        scope_layout.addWidget(self._gpu_scroll)
        layout.addWidget(scope_group)

        preview_frame = QFrame()
        preview_frame.setObjectName("previewFrame")
        preview_frame.setStyleSheet(
            "QFrame#previewFrame { background: #f5f7f8; border: 1px solid #e0e5e8;"
            " border-radius: 4px; }"
        )
        preview_layout = QVBoxLayout(preview_frame)
        preview_title = QLabel("规则预览")
        preview_title.setStyleSheet("font-weight: 600; color: #37474f;")
        self._preview_label = QLabel()
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet("color: #455a64;")
        self._preview_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        preview_layout.addWidget(preview_title)
        preview_layout.addWidget(self._preview_label)
        layout.addWidget(preview_frame)
        layout.addStretch(1)

        self._metric_combo.currentIndexChanged.connect(self._metric_changed)
        self._repeat_check.toggled.connect(self._repeat_toggled)
        self._all_radio.toggled.connect(self._scope_changed)
        for widget in (
            self._poll_spin,
            self._debounce_spin,
        ):
            widget.valueChanged.connect(self._on_edit)
        for widget in (
            self._threshold_spin,
            self._hysteresis_spin,
            self._cooldown_spin,
            self._repeat_spin,
        ):
            widget.valueChanged.connect(self._on_edit)
        self._aggregate_combo.currentIndexChanged.connect(self._on_edit)
        self._repeat_spin.setEnabled(False)

    def _metric_changed(self, *_args) -> None:
        if self._loading:
            return
        self._update_units()
        self._on_edit()

    def _update_units(self) -> None:
        percent = self._metric_combo.currentData() == "used_percent"
        for spin in (self._threshold_spin, self._hysteresis_spin):
            spin.blockSignals(True)
            if percent:
                spin.setDecimals(1)
                spin.setRange(0, 100)
                spin.setSingleStep(1)
                spin.setSuffix(" %")
            else:
                spin.setDecimals(0)
                spin.setRange(0, 4_194_304)
                spin.setSingleStep(256)
                spin.setSuffix(" MiB")
            spin.blockSignals(False)
        self._threshold_label.setText("阈值（%）" if percent else "阈值（MiB）")
        self._hysteresis_label.setText("回差（%）" if percent else "回差（MiB）")

    def _repeat_toggled(self, checked: bool) -> None:
        self._repeat_spin.setEnabled(checked)
        self._on_edit()

    def _scope_changed(self, _checked: bool) -> None:
        self._update_gpu_enabled()
        self._on_edit()

    def _update_gpu_enabled(self) -> None:
        specific = self._specific_radio.isChecked()
        self._gpu_scroll.setEnabled(specific)
        if specific and not self._gpu_names and not self._checks:
            self._gpu_hint.setText("尚未获取 GPU 列表；请先测试连接或启动监控。")
        elif specific:
            self._gpu_hint.setText("勾选参与判定的 GPU。")
        else:
            self._gpu_hint.setText("")

    def set_available_gpus(self, samples: list[GpuSample]) -> None:
        names = {sample.index: sample.name for sample in samples}
        if names == self._gpu_names:
            return
        self._gpu_names = names
        self._rebuild_gpu_checks()
        self._update_gpu_enabled()

    def _rebuild_gpu_checks(self) -> None:
        while self._gpu_layout.count():
            item = self._gpu_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._checks.clear()
        indices = sorted(set(self._gpu_names) | self._wanted_indices)
        previous = self._loading
        self._loading = True
        try:
            for position, index in enumerate(indices):
                name = self._gpu_names.get(index, "")
                label = f"GPU {index} · {name}" if name else f"GPU {index}"
                check = QCheckBox(label)
                check.setChecked(index in self._wanted_indices)
                check.toggled.connect(
                    lambda checked, idx=index: self._gpu_toggled(idx, checked)
                )
                self._gpu_layout.addWidget(check, position // 2, position % 2)
                self._checks[index] = check
        finally:
            self._loading = previous

    def _gpu_toggled(self, index: int, checked: bool) -> None:
        if checked:
            self._wanted_indices.add(index)
        else:
            self._wanted_indices.discard(index)
        if self._loading:
            return
        self._clear_validation()
        self._on_edit()

    def _on_edit(self, *_args) -> None:
        if self._loading:
            return
        self._clear_validation()
        self._update_preview()
        self.changed.emit()

    def _update_preview(self) -> None:
        self._preview_label.setText(format_rule_preview(self.collect_monitor()))

    def _clear_validation(self) -> None:
        clear_invalid(self._invalid_widgets)
        self._invalid_widgets.clear()

    def populate(self, monitor: MonitorCfg) -> None:
        self._loading = True
        try:
            self._poll_spin.setValue(monitor.poll_interval_s)
            index = self._metric_combo.findData(monitor.metric)
            self._metric_combo.setCurrentIndex(index if index >= 0 else 0)
            self._update_units()
            self._threshold_spin.setValue(monitor.threshold)
            self._hysteresis_spin.setValue(monitor.hysteresis)
            self._debounce_spin.setValue(monitor.debounce_count)
            self._cooldown_spin.setValue(monitor.cooldown_s / 60)
            self._repeat_check.setChecked(monitor.repeat_interval_s > 0)
            if monitor.repeat_interval_s > 0:
                self._repeat_spin.setValue(monitor.repeat_interval_s / 60)
            self._repeat_spin.setEnabled(self._repeat_check.isChecked())
            aggregate_index = self._aggregate_combo.findData(monitor.aggregate)
            self._aggregate_combo.setCurrentIndex(
                aggregate_index if aggregate_index >= 0 else 0
            )
            self._wanted_indices = set(monitor.gpu_filter)
            if monitor.gpu_filter:
                self._specific_radio.setChecked(True)
            else:
                self._all_radio.setChecked(True)
            self._rebuild_gpu_checks()
            self._update_gpu_enabled()
            self._clear_validation()
            self._update_preview()
        finally:
            self._loading = False

    def collect_monitor(self) -> MonitorCfg:
        metric = self._metric_combo.currentData()
        return MonitorCfg(
            poll_interval_s=self._poll_spin.value(),
            metric=metric,
            threshold=float(self._threshold_spin.value()),
            hysteresis=float(self._hysteresis_spin.value()),
            debounce_count=self._debounce_spin.value(),
            cooldown_s=int(round(self._cooldown_spin.value() * 60)),
            repeat_interval_s=(
                int(round(self._repeat_spin.value() * 60))
                if self._repeat_check.isChecked()
                else 0
            ),
            aggregate=self._aggregate_combo.currentData(),
            gpu_filter=(
                []
                if self._all_radio.isChecked()
                else sorted(self._wanted_indices)
            ),
        )

    def validate(self) -> list[tuple[QWidget, str]]:
        self._clear_validation()
        errors: list[tuple[QWidget, str]] = []
        if self._specific_radio.isChecked() and not self._wanted_indices:
            errors.append((self._specific_radio, "请至少勾选一张 GPU"))
        self._invalid_widgets = mark_invalid(errors)
        return errors
