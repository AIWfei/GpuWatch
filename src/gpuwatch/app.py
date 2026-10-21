from __future__ import annotations

import datetime as dt
import logging
from functools import partial

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from . import __version__
from .alert_engine import AlertEvent, Kind
from .config import (
    SCHEMA_VERSION,
    AppConfig,
    ConfigStore,
    validate_config,
)
from .gpu_probe import GpuSample
from .logging_setup import setup_logging
from .notifier import Notifier
from .secrets_store import SecretStoreError, get_secret, has_secret, set_secret
from .ssh_session import UnknownHostKeyError, clear_host_key, trust_host_key
from .system import set_autostart
from .ui.host_key_dialog import HostKeyDialog
from .ui.icons import app_icon, tray_icon
from .ui.main_window import MainWindow
from .worker import MonitorWorker, TestConnectionTask

log = logging.getLogger(__name__)

FATAL_CODES = {"auth_failed", "host_key_changed", "host_key_unknown", "secret_error"}
ERROR_CODES = FATAL_CODES | {"error"}


class AppController(QObject):
    def __init__(self, app: QApplication, store: ConfigStore, cfg: AppConfig):
        super().__init__()
        self.app = app
        self.store = store
        self.cfg = cfg
        self.known_hosts = store.known_hosts
        self.worker: MonitorWorker | None = None
        self.test_task: TestConnectionTask | None = None
        self.last_samples: list[GpuSample] = []
        self.has_idle = False
        self._retired: list[MonitorWorker] = []
        self._test_retry = False
        self._host_key_dialog_open = False
        self._quitting = False
        self._paused = False
        self._monitor_state = "stopped"
        self._conn_code = "stopped"
        self._conn_text = "监控未启动"

        app.setWindowIcon(app_icon())
        self.tray = QSystemTrayIcon(tray_icon("gray", False), app)
        self.tray.setToolTip("GpuWatch：监控未启动")
        self.window = MainWindow(cfg, self._secret_presence, self.tray)
        self.notifier = Notifier(self.tray, lambda: self.cfg.notify, self.window)
        self._build_tray_menu()
        self._connect_signals()
        self.tray.show()
        self._set_monitoring_state("stopped")
        self._refresh_tray_icon()
        self._update_tray_tooltip()

    # ---------- 组装 ----------
    def _secret_presence(self, kind: str) -> bool:
        return has_secret(self.cfg.server.id, kind)

    def _build_tray_menu(self) -> None:
        menu = QMenu(self.window)
        show_action = menu.addAction("显示主窗口")
        show_action.triggered.connect(self.show_window)
        self._pause_action = menu.addAction("启动监控")
        self._pause_action.triggered.connect(self.toggle_monitoring)
        self._refresh_action = menu.addAction("立即刷新")
        self._refresh_action.triggered.connect(self.refresh_now)
        self._snooze_menu = menu.addMenu("稍后提醒")
        for label, minutes in (("30 分钟", 30), ("1 小时", 60), ("2 小时", 120)):
            action = self._snooze_menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, m=minutes: self.snooze(m)
            )
        self._snooze_menu.addSeparator()
        cancel_snooze = self._snooze_menu.addAction("取消稍后提醒")
        cancel_snooze.triggered.connect(lambda: self.snooze(0))
        test_action = menu.addAction("发送测试通知")
        test_action.triggered.connect(self.send_test_notification)
        about_action = menu.addAction("关于 GpuWatch")
        about_action.triggered.connect(self.show_about)
        menu.addSeparator()
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self.quit)
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.messageClicked.connect(self.show_window)

    def _connect_signals(self) -> None:
        self.window.save_requested.connect(self.save_config)
        self.window.revert_requested.connect(self.revert_config)
        self.window.exit_requested.connect(self.quit)
        self.window.activated.connect(self._clear_idle_badge)
        self.window.shown.connect(self._clear_idle_badge)
        self.window.status_tab.refresh_requested.connect(self.refresh_now)
        self.window.status_tab.toggle_monitoring_requested.connect(
            self.toggle_monitoring
        )
        self.window.status_tab.snooze_requested.connect(self.snooze)
        self.window.status_tab.edit_connection_requested.connect(
            self.window.show_connection_tab
        )
        self.window.connection_tab.test_requested.connect(self.test_connection)
        self.window.connection_tab.clear_known_host_requested.connect(
            self.clear_trusted_host_key
        )
        self.window.general_tab.test_notification_requested.connect(
            self.send_test_notification
        )

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window()

    # ---------- 监控生命周期 ----------
    def start_worker(self) -> None:
        if self._quitting:
            return
        server = self.cfg.server
        if not server.host.strip():
            self.mark_unconfigured()
            self.show_window()
            self.window.show_connection_tab()
            self.window.show_status_message("请先在“连接”页配置服务器")
            return

        self.stop_worker()
        worker = MonitorWorker(
            self.cfg,
            partial(get_secret, server.id),
            self.known_hosts,
        )
        worker.snapshot.connect(self._on_snapshot)
        worker.status.connect(self._on_status)
        worker.alert.connect(self._on_alert)
        worker.host_key_unknown.connect(self._on_unknown_host)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(self._reap_finished_worker)
        self.worker = worker
        self.has_idle = False
        self._conn_code = "connecting"
        self._conn_text = "正在连接…"
        self.window.status_tab.set_status("connecting", "正在连接…")
        self._set_monitoring_state("running")
        self._refresh_tray_icon()
        self._update_tray_tooltip()
        worker.start()
        log.info("monitor worker started")

    def stop_worker(self) -> None:
        worker = self.worker
        self.worker = None
        if worker is None:
            return
        if worker not in self._retired:
            self._retired.append(worker)
        worker.stop()
        if worker.isFinished():
            self._reap(worker)

    def _reap(self, worker: MonitorWorker) -> None:
        if worker is self.worker:
            return
        if worker in self._retired:
            self._retired.remove(worker)
            worker.deleteLater()

    def _reap_finished_worker(self) -> None:
        worker = self.sender()
        if isinstance(worker, MonitorWorker):
            self._reap(worker)

    def _on_worker_finished(self) -> None:
        worker = self.sender()
        if worker is not self.worker or self._quitting:
            return
        log.info("monitor worker finished (last status: %s)", self._conn_code)
        if self._conn_code not in ERROR_CODES and self._conn_code != "stopped":
            self._conn_code = "stopped"
            self._conn_text = "监控已停止"
            self.window.status_tab.set_status("stopped", "监控已停止")
        self._set_monitoring_state("stopped")
        self._refresh_tray_icon()
        self._update_tray_tooltip()

    def _on_status(self, code: str, text: str) -> None:
        worker = self.sender()
        if worker is not self.worker:
            return
        self._conn_code = code
        self._conn_text = text
        self.window.status_tab.set_status(code, text)
        if code == "paused":
            self._set_monitoring_state("paused")
        elif code in FATAL_CODES or code == "stopped":
            self._set_monitoring_state("stopped")
        else:
            self._set_monitoring_state("running")
        self._refresh_tray_icon()
        self._update_tray_tooltip()
        log.info("monitor status: %s (%s)", code, text)

    def _on_snapshot(self, samples: list[GpuSample]) -> None:
        worker = self.sender()
        if worker is not self.worker:
            return
        self.last_samples = samples
        self.window.status_tab.on_snapshot(samples)
        self.window.rules_tab.set_available_gpus(samples)
        self._update_tray_tooltip()

    def _on_alert(self, event: AlertEvent) -> None:
        worker = self.sender()
        if worker is not self.worker:
            return
        self.notifier.show(event)
        if event.kind in (Kind.IDLE, Kind.REMIND):
            active = self.window.isVisible() and self.window.isActiveWindow()
            self.has_idle = not active
            self._refresh_tray_icon()
            self._update_tray_tooltip()
            self.window.show_status_message(event.title)
        elif event.kind in (Kind.DISCONNECT, Kind.ERROR):
            self.window.show_status_message(event.title, 8000)

    def _on_unknown_host(self, error: UnknownHostKeyError) -> None:
        worker = self.sender()
        if worker is not self.worker:
            return
        if self.test_task is not None:
            log.info("ignoring worker host key prompt while a test is running")
            return
        if self._host_key_dialog_open:
            return
        self._host_key_dialog_open = True
        try:
            dialog = HostKeyDialog(
                error.hostname,
                error.key.get_name(),
                error.fingerprint,
                self.window,
            )
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            self._host_key_dialog_open = False
        if not accepted:
            self.window.status_tab.set_status(
                "host_key_unknown", "已取消信任主机密钥"
            )
            self.window.show_status_message("未信任服务器主机密钥，监控保持停止")
            return
        try:
            trust_host_key(self.known_hosts, error)
        except OSError as exc:
            log.exception("failed to save trusted host key")
            QMessageBox.critical(self.window, "无法保存主机密钥", str(exc))
            return
        log.info("trusted host key for %s", error.hostname)
        self.window.show_status_message("已信任服务器主机密钥，正在重新连接")
        self.start_worker()

    # ---------- 用户操作 ----------
    def show_window(self) -> None:
        self.window.show_and_raise()
        self._clear_idle_badge()

    def _clear_idle_badge(self) -> None:
        if self.has_idle:
            self.has_idle = False
            self._refresh_tray_icon()
            self._update_tray_tooltip()

    def toggle_monitoring(self) -> None:
        if (
            self.worker is None
            or not self.worker.isRunning()
            or self.worker.isFinished()
        ):
            self.start_worker()
            return
        if self._paused:
            self.worker.pause(False)
            self._set_monitoring_state("running")
            self.window.status_tab.set_status("connecting", "正在恢复监控…")
            self.window.show_status_message("监控已恢复")
        else:
            self.worker.pause(True)
            self._set_monitoring_state("paused")
            self.window.status_tab.set_status("paused", "监控已暂停")
            self.window.show_status_message("监控已暂停")
        self._refresh_tray_icon()
        self._update_tray_tooltip()

    def refresh_now(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.poll_now()
            self.window.show_status_message("已请求立即刷新", 3000)
        else:
            self.start_worker()

    def snooze(self, minutes: int) -> None:
        if self.worker is None or not self.worker.isRunning():
            self.window.show_status_message("监控未运行，无法设置稍后提醒")
            return
        self.worker.snooze(minutes)
        if minutes <= 0:
            self.window.show_status_message("已取消稍后提醒")
        else:
            until = dt.datetime.now() + dt.timedelta(minutes=minutes)
            self.window.show_status_message(
                f"已设置稍后提醒至 {until:%H:%M}", 6000
            )

    def send_test_notification(self) -> None:
        self.notifier.show(
            AlertEvent(
                Kind.IDLE,
                "test",
                "GpuWatch 测试通知",
                "如果看到这条消息，说明桌面通知功能工作正常。",
            ),
            force=True,
        )
        self.window.show_status_message("已发送测试通知")

    def show_about(self) -> None:
        QMessageBox.about(
            self.window,
            "关于 GpuWatch",
            f"<b>GpuWatch {__version__}</b><br><br>"
            "通过 SSH 监控远程 NVIDIA GPU 显存，在显存空闲时提醒你。<br>"
            "密码与私钥口令保存在 Windows 凭据管理器中。",
        )

    def _set_monitoring_state(self, state: str) -> None:
        self._monitor_state = state
        self._paused = state == "paused"
        self.window.status_tab.set_monitoring_state(state)
        if state == "running":
            self._pause_action.setText("暂停监控")
            self._pause_action.setEnabled(True)
            self._snooze_menu.setEnabled(True)
        elif state == "paused":
            self._pause_action.setText("恢复监控")
            self._pause_action.setEnabled(True)
            self._snooze_menu.setEnabled(False)
        else:
            self._pause_action.setText("启动监控")
            self._pause_action.setEnabled(True)
            self._snooze_menu.setEnabled(False)

    def mark_unconfigured(self) -> None:
        self._conn_code = "stopped"
        self._conn_text = "未配置服务器"
        self.window.status_tab.set_status("stopped", "未配置服务器")
        self._set_monitoring_state("stopped")
        self._refresh_tray_icon()
        self._update_tray_tooltip()

    # ---------- 配置保存 ----------
    def save_config(self) -> None:
        connection = self.window.connection_tab
        rules = self.window.rules_tab
        general_tab = self.window.general_tab

        messages: list[str] = []
        first_tab: int | None = None
        for index, tab in ((1, connection), (2, rules), (3, general_tab)):
            errors = tab.validate()
            if errors:
                if first_tab is None:
                    first_tab = index
                messages.extend(message for _widget, message in errors)
        if messages:
            self.window.show_validation_errors(first_tab or 1, messages)
            return

        server = connection.collect(self.cfg.server)
        notify, general = general_tab.collect()
        new_cfg = AppConfig(
            schema_version=SCHEMA_VERSION,
            servers=[server, *self.cfg.servers[1:]],
            monitor=rules.collect_monitor(),
            notify=notify,
            general=general,
        )
        problems = validate_config(new_cfg)
        if problems:
            QMessageBox.warning(
                self.window,
                "设置无效",
                "\n".join(f"• {problem}" for problem in problems),
            )
            return

        password = connection.password_value()
        passphrase = connection.passphrase_value()
        try:
            if password:
                set_secret(server.id, "password", password)
            if passphrase:
                set_secret(server.id, "passphrase", passphrase)
        except SecretStoreError as exc:
            QMessageBox.critical(self.window, "无法保存凭据", str(exc))
            return

        was_running = bool(self.worker and self.worker.isRunning())
        try:
            self.store.save(new_cfg)
        except OSError as exc:
            log.exception("failed to save configuration")
            QMessageBox.critical(self.window, "无法保存配置", str(exc))
            return

        self.cfg = new_cfg
        setup_logging(general.log_level)
        self.window.apply_config(new_cfg)
        self._clear_idle_badge()

        autostart_error = self._apply_autostart(new_cfg)
        if general.auto_start_monitoring or was_running:
            self.start_worker()
        else:
            self.stop_worker()
            self._conn_code = "stopped"
            self._conn_text = "监控未启动"
            self.window.status_tab.set_status("stopped", "监控未启动")
            self._set_monitoring_state("stopped")
            self._refresh_tray_icon()
            self._update_tray_tooltip()
        self.window.show_status_message("设置已保存并应用", 5000)
        log.info("configuration saved and applied")
        if autostart_error:
            QMessageBox.warning(
                self.window,
                "开机自启设置失败",
                autostart_error + "\n其他设置已保存。",
            )

    def revert_config(self) -> None:
        self.window.apply_config(self.cfg)
        self.window.show_status_message("已还原为上次保存的设置", 4000)

    def _apply_autostart(self, cfg: AppConfig) -> str | None:
        try:
            set_autostart(
                cfg.general.start_with_windows,
                cfg.general.start_minimized,
            )
        except OSError as exc:
            log.exception("failed to update autostart")
            return str(exc)
        return None

    def sync_autostart(self) -> None:
        error = self._apply_autostart(self.cfg)
        if error:
            log.warning("autostart sync failed: %s", error)

    # ---------- 测试连接 / 主机密钥 ----------
    def test_connection(self) -> None:
        if self.test_task is not None:
            return
        connection = self.window.connection_tab
        errors = connection.validate()
        if errors:
            self.window.show_validation_errors(
                1, [message for _widget, message in errors]
            )
            return

        server = connection.collect(self.cfg.server)
        password = connection.password_value()
        passphrase = connection.passphrase_value()

        def get_secret_override(kind: str) -> str | None:
            if kind == "password" and password:
                return password
            if kind == "passphrase" and passphrase:
                return passphrase
            return get_secret(server.id, kind)

        task = TestConnectionTask(server, get_secret_override, self.known_hosts)
        task.ok.connect(self._on_test_ok)
        task.failed.connect(self._on_test_failed)
        task.unknown_host.connect(self._on_test_unknown_host)
        task.finished.connect(self._on_test_finished)
        self.test_task = task
        connection.set_testing(True)
        task.start()

    def _on_test_ok(self, samples: list[GpuSample]) -> None:
        task = self.sender()
        if task is not self.test_task or self._quitting:
            return
        self.window.connection_tab.show_test_success(samples)
        self.window.rules_tab.set_available_gpus(samples)
        self.window.show_status_message(
            f"测试连接成功，检测到 {len(samples)} 张 GPU", 5000
        )
        log.info("test connection succeeded: %s gpus", len(samples))

    def _on_test_failed(self, message: str) -> None:
        task = self.sender()
        if task is not self.test_task or self._quitting:
            return
        self.window.connection_tab.show_test_failure(message)
        self.window.show_status_message(message, 8000)
        log.warning("test connection failed: %s", message)

    def _on_test_unknown_host(self, error: UnknownHostKeyError) -> None:
        task = self.sender()
        if task is not self.test_task or self._quitting:
            return
        if self._host_key_dialog_open:
            self.window.connection_tab.set_info(
                "主机密钥未信任，请先完成指纹确认", error=True
            )
            return
        self._host_key_dialog_open = True
        try:
            dialog = HostKeyDialog(
                error.hostname,
                error.key.get_name(),
                error.fingerprint,
                self.window,
            )
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            self._host_key_dialog_open = False
        if not accepted:
            self.window.connection_tab.set_info(
                "已取消主机密钥确认", error=True
            )
            return
        try:
            trust_host_key(self.known_hosts, error)
        except OSError as exc:
            log.exception("failed to save trusted host key")
            self.window.connection_tab.show_test_failure(
                f"无法保存主机密钥：{exc}"
            )
            return
        log.info("trusted host key for %s (from test)", error.hostname)
        self.window.connection_tab.set_info(
            "已信任主机密钥，正在重新测试连接…"
        )
        self._test_retry = True
        if (
            self.worker is not None
            and self.worker.isFinished()
            and self._conn_code == "host_key_unknown"
        ):
            self.start_worker()

    def _on_test_finished(self) -> None:
        task = self.sender()
        if task is not self.test_task:
            return
        self.test_task = None
        self.window.connection_tab.set_testing(False)
        if isinstance(task, TestConnectionTask):
            task.deleteLater()
        if self._test_retry and not self._quitting:
            self._test_retry = False
            QTimer.singleShot(0, self.test_connection)

    def clear_trusted_host_key(self) -> None:
        server = self.window.connection_tab.collect(self.cfg.server)
        if not server.host:
            QMessageBox.warning(
                self.window, "无法清除", "请先填写服务器主机地址。"
            )
            return
        answer = QMessageBox.question(
            self.window,
            "清除已信任指纹",
            f"确定要清除 {server.host}:{server.port} 的主机密钥记录吗？\n"
            "下次连接时需要重新确认服务器指纹。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            removed = clear_host_key(self.known_hosts, server.host, server.port)
        except OSError as exc:
            log.exception("failed to clear known host key")
            QMessageBox.critical(self.window, "清除失败", str(exc))
            return
        if removed:
            self.window.connection_tab.set_info(
                "已清除该服务器的主机密钥记录，下次连接需要重新确认指纹。"
            )
            log.info("cleared host key for %s:%s", server.host, server.port)
        else:
            self.window.connection_tab.set_info(
                "没有找到该服务器已信任的主机密钥记录。"
            )

    # ---------- 托盘外观 ----------
    def _refresh_tray_icon(self) -> None:
        if self._conn_code in ERROR_CODES:
            state = "error"
        elif self._conn_code == "connected":
            state = "connected"
        else:
            state = "gray"
        badge = self.has_idle and state == "connected"
        self.tray.setIcon(tray_icon(state, badge))

    def _update_tray_tooltip(self) -> None:
        code = self._conn_code
        if code == "paused":
            text = "GpuWatch：监控已暂停"
        elif code == "stopped":
            text = f"GpuWatch：{self._conn_text}"
        elif code in ERROR_CODES:
            text = f"GpuWatch：{self._conn_text}"
        elif code == "connected":
            if self.last_samples:
                percentages = [
                    sample.used_percent
                    for sample in self.last_samples
                    if sample.used_percent is not None
                ]
                text = f"GpuWatch：已连接，{len(self.last_samples)} 张 GPU"
                if percentages:
                    text += f"，最低占用 {min(percentages):.0f}%"
                if self.has_idle:
                    text += "（有空闲显存）"
            else:
                text = "GpuWatch：已连接"
        else:
            text = f"GpuWatch：{self._conn_text}"
        self.tray.setToolTip(text[:127])

    # ---------- 退出 ----------
    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        log.info("application shutting down")
        self.window.quitting = True
        self.stop_worker()
        task = self.test_task
        if task is not None and task.isRunning():
            task.wait(3000)
        self.tray.hide()
        self.app.quit()
