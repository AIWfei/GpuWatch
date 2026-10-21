from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import paramiko
from PySide6.QtCore import QThread, Signal

from .alert_engine import AlertEngine, AlertEvent, Kind, in_quiet_hours
from .gpu_probe import ProbeError, query_gpus
from .secrets_store import SecretStoreError
from .ssh_session import Backoff, SshSession, UnknownHostKeyError

log = logging.getLogger(__name__)


class MonitorWorker(QThread):
    snapshot = Signal(object)
    status = Signal(str, str)
    alert = Signal(object)
    host_key_unknown = Signal(object)

    def __init__(self, cfg, get_secret, known_hosts: Path, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.srv = cfg.server
        self.ssh = SshSession(self.srv, get_secret, known_hosts)
        self.engine = AlertEngine(
            cfg.monitor, cfg.notify.notify_on_busy_again, self.srv.name
        )
        self._stopping = False
        self._paused = False
        self._wake = threading.Event()
        self._snooze_until = 0.0
        self._was_suppressed = False
        self._backoff = Backoff()
        self._fails = 0
        self._down_notified = False
        self._down_code: str | None = None

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        self.ssh.close()
        timeout_ms = max(5000, int((self.srv.connect_timeout_s + 5) * 1000))
        if not self.wait(timeout_ms):
            log.warning("monitor worker still running after %s ms", timeout_ms)

    def pause(self, on: bool) -> None:
        self._paused = bool(on)
        self._wake.set()

    def snooze(self, minutes: int) -> None:
        if minutes <= 0:
            self._snooze_until = 0.0
        else:
            self._snooze_until = time.monotonic() + minutes * 60
        log.info("snooze set for %s minutes", minutes)

    def poll_now(self) -> None:
        self._wake.set()

    def run(self) -> None:
        log.info("monitor worker started for %s:%s", self.srv.host, self.srv.port)
        try:
            while not self._stopping:
                wait = max(1, int(self.cfg.monitor.poll_interval_s))
                if self._paused:
                    self.status.emit("paused", "监控已暂停")
                else:
                    try:
                        self._tick()
                    except UnknownHostKeyError as exc:
                        if self._stopping:
                            break
                        log.warning("unknown host key for %s", exc.hostname)
                        self.status.emit("host_key_unknown", "主机密钥未信任，等待确认")
                        self.host_key_unknown.emit(exc)
                        return
                    except paramiko.BadHostKeyException:
                        self._fatal(
                            "host_key_changed",
                            "服务器主机密钥已变化，已停止连接（可能存在中间人攻击）",
                        )
                        return
                    except paramiko.AuthenticationException as exc:
                        self._fatal(
                            "auth_failed", f"认证失败，请检查用户名、密码或私钥（{exc}）"
                        )
                        return
                    except paramiko.PasswordRequiredException:
                        self._fatal(
                            "auth_failed",
                            "私钥需要口令，请在连接设置中填写私钥口令",
                        )
                        return
                    except SecretStoreError as exc:
                        self._fatal("secret_error", str(exc))
                        return
                    except ProbeError as exc:
                        if self._stopping:
                            break
                        self._on_failure("probe_error", str(exc))
                    except (OSError, EOFError, paramiko.SSHException) as exc:
                        if self._stopping:
                            break
                        self.ssh.close()
                        wait = self._backoff.next()
                        self._on_failure(
                            "reconnecting", f"连接失败：{exc}，{wait} 秒后重试"
                        )
                        log.warning("ssh failure: %s; retry in %s s", exc, wait)
                    except Exception:
                        if self._stopping:
                            break
                        log.exception("unexpected error in monitor worker")
                        wait = 30
                        self.status.emit("error", "内部错误，详见日志")
                self._wake.wait(wait)
                self._wake.clear()
            self.status.emit("stopped", "已停止")
        finally:
            self.ssh.close()
            log.info("monitor worker stopped")

    def _tick(self) -> None:
        if not self.ssh.is_alive():
            self.status.emit("connecting", "正在连接…")
            self.ssh.connect()
        samples = query_gpus(self.ssh, self.srv)
        self._on_success()
        self.snapshot.emit(samples)

        now = time.monotonic()
        suppressed = now < self._snooze_until or in_quiet_hours(
            self.cfg.notify.quiet_hours
        )
        if suppressed:
            self._was_suppressed = True
            return
        resumed = self._was_suppressed
        self._was_suppressed = False
        for event in self.engine.feed(samples, now, resumed=resumed):
            log.info("alert %s %s", event.kind.value, event.key)
            self.alert.emit(event)

    def _on_success(self) -> None:
        self._backoff.reset()
        if self._down_notified and self.cfg.notify.notify_on_disconnect:
            if self._down_code == "probe_error":
                title = f"{self.srv.name} 采样已恢复"
            else:
                title = f"{self.srv.name} 连接已恢复"
            self.alert.emit(
                AlertEvent(Kind.RECOVER, "conn", title, "监控恢复正常")
            )
        self._fails = 0
        self._down_notified = False
        self._down_code = None
        self.status.emit("connected", "已连接")

    def _on_failure(self, code: str, text: str) -> None:
        self._fails += 1
        self.status.emit(code, text)
        notify = self.cfg.notify
        if (
            notify.notify_on_disconnect
            and self._fails >= notify.disconnect_after_failures
            and not self._down_notified
        ):
            self._down_notified = True
            self._down_code = code
            title = (
                f"{self.srv.name} 采样失败"
                if code == "probe_error"
                else f"{self.srv.name} 连接中断"
            )
            self.alert.emit(AlertEvent(Kind.DISCONNECT, "conn", title, text))

    def _fatal(self, code: str, text: str) -> None:
        log.error("fatal monitor error [%s]: %s", code, text)
        self.status.emit(code, text)
        self.alert.emit(
            AlertEvent(Kind.ERROR, "fatal", f"{self.srv.name} 监控已停止", text)
        )


class TestConnectionTask(QThread):
    ok = Signal(object)
    failed = Signal(str)
    unknown_host = Signal(object)

    def __init__(self, server, get_secret, known_hosts: Path, parent=None):
        super().__init__(parent)
        self.server = server
        self.get_secret = get_secret
        self.known_hosts = known_hosts

    def run(self) -> None:
        ssh = SshSession(self.server, self.get_secret, self.known_hosts)
        try:
            ssh.connect()
            samples = query_gpus(ssh, self.server)
            self.ok.emit(samples)
        except UnknownHostKeyError as exc:
            self.unknown_host.emit(exc)
        except paramiko.AuthenticationException:
            self.failed.emit("认证失败：用户名、密码或私钥不正确")
        except paramiko.BadHostKeyException:
            self.failed.emit("主机密钥与已信任记录不一致")
        except ProbeError as exc:
            self.failed.emit(str(exc))
        except SecretStoreError as exc:
            self.failed.emit(str(exc))
        except (OSError, EOFError, paramiko.SSHException) as exc:
            self.failed.emit(f"连接失败：{exc}")
        except Exception as exc:
            log.exception("unexpected error in test connection")
            self.failed.emit(f"连接失败：{exc}")
        finally:
            ssh.close()
