from __future__ import annotations

import logging

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

log = logging.getLogger(__name__)

SERVICE = "GpuWatch"
SECRET_KINDS = ("password", "passphrase")


class SecretStoreError(RuntimeError):
    pass


def _account(server_id: str, kind: str) -> str:
    if kind not in SECRET_KINDS:
        raise ValueError(f"unknown secret kind: {kind}")
    return f"{server_id}:{kind}"


def get_secret(server_id: str, kind: str) -> str | None:
    try:
        return keyring.get_password(SERVICE, _account(server_id, kind))
    except KeyringError as exc:
        raise SecretStoreError(f"无法访问 Windows 凭据管理器：{exc}") from exc


def has_secret(server_id: str, kind: str) -> bool:
    try:
        return bool(get_secret(server_id, kind))
    except SecretStoreError:
        log.warning("credential manager unavailable while checking %s", kind)
        return False


def set_secret(server_id: str, kind: str, value: str) -> None:
    try:
        if value:
            keyring.set_password(SERVICE, _account(server_id, kind), value)
        else:
            try:
                keyring.delete_password(SERVICE, _account(server_id, kind))
            except PasswordDeleteError:
                pass
    except KeyringError as exc:
        raise SecretStoreError(f"无法写入 Windows 凭据管理器：{exc}") from exc
