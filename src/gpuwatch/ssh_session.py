from __future__ import annotations

import base64
import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import paramiko

log = logging.getLogger(__name__)


class UnknownHostKeyError(Exception):
    def __init__(self, hostname: str, key: paramiko.PKey):
        super().__init__(f"unknown host key: {hostname}")
        self.hostname = hostname
        self.key = key

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256(self.key.asbytes()).digest()
        return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


class _RaiseOnUnknown(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        raise UnknownHostKeyError(hostname, key)


def host_key_name(host: str, port: int) -> str:
    return host if port == 22 else f"[{host}]:{port}"


def trust_host_key(known_hosts: Path, err: UnknownHostKeyError) -> None:
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    host_keys = paramiko.HostKeys()
    if known_hosts.exists():
        host_keys.load(str(known_hosts))
    host_keys.add(err.hostname, err.key.get_name(), err.key)
    host_keys.save(str(known_hosts))


def clear_host_key(known_hosts: Path, host: str, port: int) -> bool:
    if not known_hosts.exists():
        return False
    host_keys = paramiko.HostKeys()
    try:
        host_keys.load(str(known_hosts))
    except (OSError, paramiko.SSHException):
        log.exception("failed to read known_hosts")
        return False
    name = host_key_name(host, port)
    removed = host_keys.pop(name, None) is not None
    if removed:
        host_keys.save(str(known_hosts))
    return removed


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str


class SshSession:
    def __init__(self, server, get_secret, known_hosts: Path):
        self.server = server
        self._get_secret = get_secret
        self._known_hosts = Path(known_hosts)
        self._client: paramiko.SSHClient | None = None

    def connect(self) -> None:
        self.close()
        self._known_hosts.parent.mkdir(parents=True, exist_ok=True)
        self._known_hosts.touch(exist_ok=True)

        client = paramiko.SSHClient()
        client.load_host_keys(str(self._known_hosts))
        client.set_missing_host_key_policy(_RaiseOnUnknown())

        timeout = self.server.connect_timeout_s
        kwargs = dict(
            hostname=self.server.host,
            port=self.server.port,
            username=self.server.username,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
            look_for_keys=False,
            allow_agent=False,
        )
        if self.server.auth_type == "password":
            password = self._get_secret("password")
            if not password:
                raise paramiko.AuthenticationException(
                    "没有已保存的密码，请在连接设置中重新输入"
                )
            kwargs["password"] = password
        else:
            key_path = os.path.expanduser(self.server.key_path)
            if not os.path.isfile(key_path):
                raise paramiko.SSHException(f"私钥文件不存在：{key_path}")
            kwargs["key_filename"] = key_path
            kwargs["passphrase"] = self._get_secret("passphrase") or None

        self._client = client
        try:
            client.connect(**kwargs)
            if self._client is not client:
                raise ConnectionError("ssh connect cancelled")
            transport = client.get_transport()
            if transport is not None:
                transport.set_keepalive(30)
        except BaseException:
            client.close()
            if self._client is client:
                self._client = None
            raise

        log.info(
            "ssh connected to %s@%s:%s",
            self.server.username,
            self.server.host,
            self.server.port,
        )

    def is_alive(self) -> bool:
        transport = self._client.get_transport() if self._client else None
        return bool(transport and transport.is_active())

    def exec(self, cmd: str, timeout: float = 20) -> ExecResult:
        if not self.is_alive() or self._client is None:
            raise ConnectionError("ssh session is not connected")
        _stdin, stdout, stderr = self._client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        return ExecResult(stdout.channel.recv_exit_status(), out, err)

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                log.debug("error while closing ssh session", exc_info=True)
            self._client = None


class Backoff:
    STEPS = (5, 10, 20, 40, 80, 160, 300)

    def __init__(self) -> None:
        self.n = 0

    def next(self) -> int:
        delay = self.STEPS[min(self.n, len(self.STEPS) - 1)]
        self.n += 1
        return delay

    def reset(self) -> None:
        self.n = 0
