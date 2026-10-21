from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import ServerCfg
from ..gpu_probe import GpuSample
from .common import clear_invalid, format_mib_pair, mark_invalid


class ConnectionTab(QWidget):
    changed = Signal()
    test_requested = Signal()
    clear_known_host_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._has_password = False
        self._has_passphrase = False
        self._invalid_widgets: list[QWidget] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        server_group = QGroupBox("服务器")
        server_form = QFormLayout(server_group)
        server_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self._name_edit = QLineEdit()
        self._host_edit = QLineEdit()
        self._host_edit.setPlaceholderText("例如 10.0.0.8 或 gpu.example.com")
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(22)
        host_row = QHBoxLayout()
        host_row.addWidget(self._host_edit, 1)
        host_row.addWidget(QLabel("端口"))
        host_row.addWidget(self._port_spin)
        self._username_edit = QLineEdit()
        server_form.addRow("服务器名称", self._name_edit)
        server_form.addRow("主机", host_row)
        server_form.addRow("用户名", self._username_edit)
        layout.addWidget(server_group)

        auth_group = QGroupBox("认证方式")
        auth_layout = QVBoxLayout(auth_group)
        radio_row = QHBoxLayout()
        self._password_radio = QRadioButton("密码认证")
        self._key_radio = QRadioButton("私钥认证")
        self._password_radio.setChecked(True)
        radio_row.addWidget(self._password_radio)
        radio_row.addWidget(self._key_radio)
        radio_row.addStretch(1)
        auth_layout.addLayout(radio_row)

        self._password_box = QWidget()
        password_form = QFormLayout(self._password_box)
        password_form.setContentsMargins(0, 0, 0, 0)
        password_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        password_row = QHBoxLayout()
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._show_password = QCheckBox("显示")
        password_row.addWidget(self._password_edit, 1)
        password_row.addWidget(self._show_password)
        password_hint = QLabel("密码保存在 Windows 凭据管理器，不会写入配置文件。")
        password_hint.setStyleSheet("color: #78909c;")
        password_hint.setWordWrap(True)
        password_form.addRow("密码", password_row)
        password_form.addRow("", password_hint)
        auth_layout.addWidget(self._password_box)

        self._key_box = QWidget()
        key_form = QFormLayout(self._key_box)
        key_form.setContentsMargins(0, 0, 0, 0)
        key_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        key_row = QHBoxLayout()
        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText("OpenSSH / PEM 格式私钥")
        self._browse_btn = QPushButton("浏览…")
        key_row.addWidget(self._key_edit, 1)
        key_row.addWidget(self._browse_btn)
        self._passphrase_edit = QLineEdit()
        self._passphrase_edit.setEchoMode(QLineEdit.EchoMode.Password)
        key_hint = QLabel(
            "支持 OpenSSH / PEM 私钥；PuTTY .ppk 请先用 PuTTYgen 转换为 OpenSSH 格式。"
        )
        key_hint.setStyleSheet("color: #78909c;")
        key_hint.setWordWrap(True)
        key_form.addRow("私钥文件", key_row)
        key_form.addRow("私钥口令", self._passphrase_edit)
        key_form.addRow("", key_hint)
        auth_layout.addWidget(self._key_box)
        layout.addWidget(auth_group)

        advanced_group = QGroupBox("高级")
        advanced_form = QFormLayout(advanced_group)
        self._smi_edit = QLineEdit()
        self._smi_edit.setPlaceholderText("nvidia-smi")
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(1, 120)
        self._timeout_spin.setSuffix(" 秒")
        self._timeout_spin.setValue(10)
        smi_hint = QLabel("提示“找不到 nvidia-smi”时可填写完整路径，如 /usr/bin/nvidia-smi。")
        smi_hint.setStyleSheet("color: #78909c;")
        smi_hint.setWordWrap(True)
        advanced_form.addRow("nvidia-smi 路径", self._smi_edit)
        advanced_form.addRow("连接超时", self._timeout_spin)
        advanced_form.addRow("", smi_hint)
        layout.addWidget(advanced_group)

        buttons = QHBoxLayout()
        self._test_btn = QPushButton("测试连接")
        self._clear_trust_btn = QPushButton("清除已信任指纹")
        buttons.addWidget(self._test_btn)
        buttons.addWidget(self._clear_trust_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._result_label = QLabel("")
        self._result_label.setWordWrap(True)
        self._result_label.setStyleSheet("color: #546e7a;")
        layout.addWidget(self._result_label)

        self._gpu_group = QGroupBox("检测到的 GPU")
        gpu_layout = QVBoxLayout(self._gpu_group)
        self._gpu_list = QListWidget()
        self._gpu_list.setMinimumHeight(70)
        self._gpu_list.setMaximumHeight(150)
        gpu_layout.addWidget(self._gpu_list)
        self._gpu_group.hide()
        layout.addWidget(self._gpu_group)
        layout.addStretch(1)

        self._password_radio.toggled.connect(self._auth_changed)
        self._show_password.toggled.connect(self._toggle_password_echo)
        self._browse_btn.clicked.connect(self._browse_key)
        self._test_btn.clicked.connect(self._on_test_clicked)
        self._clear_trust_btn.clicked.connect(
            lambda: self.clear_known_host_requested.emit()
        )
        for edit in (
            self._name_edit,
            self._host_edit,
            self._username_edit,
            self._password_edit,
            self._key_edit,
            self._passphrase_edit,
            self._smi_edit,
        ):
            edit.textChanged.connect(self._on_edit)
        self._port_spin.valueChanged.connect(self._on_edit)
        self._timeout_spin.valueChanged.connect(self._on_edit)

        self._update_auth_mode()

    def _auth_changed(self, _checked: bool) -> None:
        self._update_auth_mode()
        self._on_edit()

    def _update_auth_mode(self) -> None:
        password = self._password_radio.isChecked()
        self._password_box.setVisible(password)
        self._key_box.setVisible(not password)

    def _toggle_password_echo(self, visible: bool) -> None:
        self._password_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )

    def _browse_key(self) -> None:
        start_dir = str(Path.home() / ".ssh")
        if self._key_edit.text().strip():
            candidate = Path(self._key_edit.text().strip()).expanduser().parent
            if candidate.is_dir():
                start_dir = str(candidate)
        path, _ = QFileDialog.getOpenFileName(
            self, "选择私钥文件", start_dir, "私钥文件 (*);;所有文件 (*)"
        )
        if path:
            self._key_edit.setText(path)

    def _on_edit(self, *_args) -> None:
        if self._loading:
            return
        self._clear_validation()
        self.changed.emit()

    def _clear_validation(self) -> None:
        clear_invalid(self._invalid_widgets)
        self._invalid_widgets.clear()

    def populate(
        self, server: ServerCfg, has_password: bool, has_passphrase: bool
    ) -> None:
        self._loading = True
        try:
            self._name_edit.setText(server.name)
            self._host_edit.setText(server.host)
            self._port_spin.setValue(server.port)
            self._username_edit.setText(server.username)
            if server.auth_type == "key":
                self._key_radio.setChecked(True)
            else:
                self._password_radio.setChecked(True)
            self._key_edit.setText(server.key_path)
            self._smi_edit.setText(server.nvidia_smi_path)
            self._timeout_spin.setValue(server.connect_timeout_s)
            self._password_edit.clear()
            self._passphrase_edit.clear()
            self._show_password.setChecked(False)
            self._set_secret_presence(has_password, has_passphrase)
            self._update_auth_mode()
            self._clear_validation()
        finally:
            self._loading = False

    def set_secret_presence(self, has_password: bool, has_passphrase: bool) -> None:
        self._set_secret_presence(has_password, has_passphrase)

    def _set_secret_presence(self, has_password: bool, has_passphrase: bool) -> None:
        self._has_password = has_password
        self._has_passphrase = has_passphrase
        self._password_edit.setPlaceholderText(
            "已保存，留空表示不修改" if has_password else "请输入密码"
        )
        self._passphrase_edit.setPlaceholderText(
            "已保存，留空表示不修改" if has_passphrase else "如私钥有口令请输入"
        )

    def password_value(self) -> str:
        return self._password_edit.text()

    def passphrase_value(self) -> str:
        return self._passphrase_edit.text()

    def collect(self, base: ServerCfg | None = None) -> ServerCfg:
        base = base or ServerCfg()
        return ServerCfg(
            id=base.id,
            name=self._name_edit.text().strip(),
            host=self._host_edit.text().strip(),
            port=self._port_spin.value(),
            username=self._username_edit.text().strip(),
            auth_type="password" if self._password_radio.isChecked() else "key",
            key_path=self._key_edit.text().strip(),
            connect_timeout_s=self._timeout_spin.value(),
            nvidia_smi_path=self._smi_edit.text().strip(),
        )

    def validate(self) -> list[tuple[QWidget, str]]:
        self._clear_validation()
        errors: list[tuple[QWidget, str]] = []
        if not self._name_edit.text().strip():
            errors.append((self._name_edit, "请填写服务器名称"))
        if not self._host_edit.text().strip():
            errors.append((self._host_edit, "请填写服务器主机地址"))
        if not self._username_edit.text().strip():
            errors.append((self._username_edit, "请填写 SSH 用户名"))
        if self._password_radio.isChecked():
            if not self._password_edit.text() and not self._has_password:
                errors.append((self._password_edit, "请输入密码"))
        else:
            key_path = self._key_edit.text().strip()
            if not key_path:
                errors.append((self._key_edit, "请选择私钥文件"))
            elif not Path(key_path).expanduser().is_file():
                errors.append((self._key_edit, "私钥文件不存在"))
        if not self._smi_edit.text().strip():
            errors.append((self._smi_edit, "请填写 nvidia-smi 路径"))
        self._invalid_widgets = mark_invalid(errors)
        return errors

    def _on_test_clicked(self) -> None:
        self.test_requested.emit()

    def set_testing(self, testing: bool) -> None:
        self._test_btn.setEnabled(not testing)
        self._clear_trust_btn.setEnabled(not testing)
        self._test_btn.setText("测试中…" if testing else "测试连接")
        if testing:
            self.set_info("正在连接服务器并执行 nvidia-smi…")

    def set_info(self, text: str, error: bool = False) -> None:
        color = "#c62828" if error else "#546e7a"
        self._result_label.setStyleSheet(f"color: {color};")
        self._result_label.setText(text)

    def show_test_success(self, samples: list[GpuSample]) -> None:
        self.set_info(f"连接成功，检测到 {len(samples)} 张 GPU。", error=False)
        self._gpu_list.clear()
        for sample in sorted(samples, key=lambda item: item.index):
            memory = format_mib_pair(sample.mem_used_mib, sample.mem_total_mib)
            self._gpu_list.addItem(
                f"GPU {sample.index} · {sample.name} · {memory}"
            )
        self._gpu_group.show()

    def show_test_failure(self, message: str) -> None:
        self.set_info(message, error=True)
        self._gpu_list.clear()
        self._gpu_group.hide()
