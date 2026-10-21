from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QStyle,
    QVBoxLayout,
    QWidget,
)


class HostKeyDialog(QDialog):
    def __init__(
        self,
        hostname: str,
        algorithm: str,
        fingerprint: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("确认服务器主机密钥")
        self.setMinimumWidth(560)
        self._build_ui(hostname, algorithm, fingerprint)

    def _build_ui(self, hostname: str, algorithm: str, fingerprint: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        header = QHBoxLayout()
        icon_label = QLabel()
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        icon_label.setPixmap(icon.pixmap(48, 48))
        icon_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
        )
        title = QLabel("首次连接，需要确认服务器身份")
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        title.setFont(font)
        title.setWordWrap(True)
        header.addWidget(icon_label)
        header.addWidget(title, 1)
        layout.addLayout(header)

        info = QLabel(
            f"服务器：{hostname}\n"
            f"密钥算法：{algorithm}\n"
            f"SHA256 指纹：{fingerprint}"
        )
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info.setStyleSheet(
            "background: #f5f7f8; border: 1px solid #e0e5e8; border-radius: 4px;"
            " padding: 10px; font-family: Consolas, monospace;"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        instructions = QLabel(
            "请在服务器上执行以下命令并核对指纹：\n"
            "ssh-keygen -lf /etc/ssh/ssh_host_*_key.pub\n\n"
            "如果指纹与上面不一致，请勿继续——可能连接到了错误的服务器，"
            "或存在中间人攻击。信任后若服务器指纹发生变化，程序将拒绝连接。"
        )
        instructions.setWordWrap(True)
        instructions.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(instructions)

        buttons = QDialogButtonBox()
        trust = buttons.addButton(
            "信任并继续", QDialogButtonBox.ButtonRole.AcceptRole
        )
        cancel = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        trust.setDefault(False)
        cancel.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
