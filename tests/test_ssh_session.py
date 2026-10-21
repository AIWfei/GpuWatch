from __future__ import annotations

import base64
import hashlib

import paramiko
import pytest

from gpuwatch.ssh_session import (
    Backoff,
    UnknownHostKeyError,
    clear_host_key,
    host_key_name,
    trust_host_key,
)


@pytest.fixture(scope="module")
def host_key() -> paramiko.RSAKey:
    return paramiko.RSAKey.generate(1024)


def test_fingerprint_is_sha256(host_key):
    err = UnknownHostKeyError("[10.0.0.8]:2222", host_key)
    expected = base64.b64encode(hashlib.sha256(host_key.asbytes()).digest())
    assert err.fingerprint == "SHA256:" + expected.decode().rstrip("=")


def test_trust_and_clear_host_key(host_key, tmp_path):
    known_hosts = tmp_path / "known_hosts"
    err = UnknownHostKeyError("[10.0.0.8]:2222", host_key)
    trust_host_key(known_hosts, err)

    loaded = paramiko.HostKeys(str(known_hosts))
    assert loaded["[10.0.0.8]:2222"][host_key.get_name()] == host_key

    assert clear_host_key(known_hosts, "10.0.0.8", 2222) is True
    assert clear_host_key(known_hosts, "10.0.0.8", 2222) is False


def test_host_key_name_uses_brackets_for_custom_port():
    assert host_key_name("gpu.example.com", 22) == "gpu.example.com"
    assert host_key_name("gpu.example.com", 2222) == "[gpu.example.com]:2222"


def test_clear_host_key_missing_file(tmp_path):
    assert clear_host_key(tmp_path / "missing", "host", 22) is False


def test_backoff_sequence_and_reset():
    backoff = Backoff()
    assert [backoff.next() for _ in range(9)] == [5, 10, 20, 40, 80, 160, 300, 300, 300]
    backoff.reset()
    assert backoff.next() == 5
