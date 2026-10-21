from __future__ import annotations

import json

import pytest

from gpuwatch.config import (
    AppConfig,
    ConfigStore,
    MonitorCfg,
    ServerCfg,
    from_dict,
    normalize_config,
    validate_config,
)


def test_missing_fields_use_defaults():
    cfg = from_dict(AppConfig, {"monitor": {"threshold": 30}})
    assert cfg.monitor.threshold == 30
    assert cfg.monitor.poll_interval_s == 10
    assert cfg.monitor.aggregate == "per_gpu"
    assert cfg.notify.enabled is True
    assert cfg.notify.quiet_hours.start == "23:00"
    assert cfg.general.close_to_tray is True
    assert cfg.server.host == ""


def test_unknown_fields_are_ignored():
    cfg = from_dict(
        AppConfig,
        {
            "schema_version": 1,
            "future_option": True,
            "monitor": {"threshold": 12, "unknown_nested": "x"},
            "servers": [{"host": "10.0.0.8", "extra": "ignored"}],
        },
    )
    assert cfg.monitor.threshold == 12
    assert cfg.server.host == "10.0.0.8"
    assert not hasattr(cfg.monitor, "unknown_nested")


def test_invalid_field_values_fall_back_to_defaults():
    cfg = from_dict(AppConfig, {"servers": [{"port": "not-a-number"}]})
    assert cfg.server.port == 22
    cfg2 = from_dict(AppConfig, {"monitor": {"debounce_count": None}})
    assert cfg2.monitor.debounce_count == 3


def test_bad_json_is_backed_up_and_defaults_returned(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ this is not json", "utf-8")
    store = ConfigStore(path)
    cfg = store.load()
    assert cfg == AppConfig()
    assert not path.exists()
    backup = tmp_path / "config.json.bak"
    assert backup.exists()
    assert "not json" in backup.read_text("utf-8")


def test_non_object_json_is_treated_as_corrupt(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]", "utf-8")
    cfg = ConfigStore(path).load()
    assert cfg == AppConfig()
    assert (tmp_path / "config.json.bak").exists()


def test_missing_config_file_returns_defaults(tmp_path):
    assert ConfigStore(tmp_path / "nope.json").load() == AppConfig()


def test_save_load_round_trip(tmp_path):
    store = ConfigStore(tmp_path / "config.json", tmp_path / "known_hosts")
    cfg = AppConfig()
    cfg.servers[0] = ServerCfg(
        id="default",
        name="实验室服务器",
        host="10.0.0.8",
        port=2222,
        username="ubuntu",
        auth_type="key",
        key_path="C:/Users/me/.ssh/id_ed25519",
        nvidia_smi_path="/usr/bin/nvidia-smi",
    )
    cfg.monitor = MonitorCfg(
        poll_interval_s=30,
        metric="free_mib",
        threshold=20480,
        hysteresis=1024,
        debounce_count=2,
        cooldown_s=1200,
        repeat_interval_s=3600,
        aggregate="all",
        gpu_filter=[2, 0, 2],
    )
    cfg.notify.quiet_hours.enabled = True
    cfg.notify.quiet_hours.start = "22:30"
    cfg.general.start_with_windows = True

    store.save(cfg)
    loaded = store.load()
    assert loaded.server.name == "实验室服务器"
    assert loaded.server.port == 2222
    assert loaded.monitor.metric == "free_mib"
    assert loaded.monitor.gpu_filter == [0, 2]
    assert loaded.notify.quiet_hours.start == "22:30"
    assert loaded.general.start_with_windows is True
    assert loaded == cfg


def test_saved_json_contains_no_secret_fields(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.save(AppConfig())
    data = json.loads((tmp_path / "config.json").read_text("utf-8"))
    assert data["schema_version"] == 1

    keys: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            keys.update(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    assert "password" not in keys
    assert "passphrase" not in keys
    assert "secret" not in keys


def test_normalize_sorts_and_deduplicates_gpu_filter():
    cfg = AppConfig()
    cfg.monitor.gpu_filter = [3, 1, 3, 0]
    normalize_config(cfg)
    assert cfg.monitor.gpu_filter == [0, 1, 3]


def test_normalize_restores_missing_server_list():
    cfg = AppConfig()
    cfg.servers = []
    normalize_config(cfg)
    assert len(cfg.servers) == 1


def test_validate_accepts_default_config_with_host():
    cfg = AppConfig()
    cfg.server.host = "10.0.0.8"
    cfg.server.username = "ubuntu"
    assert validate_config(cfg) == []


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda c: setattr(c.server, "host", ""), "服务器地址"),
        (lambda c: setattr(c.server, "username", ""), "用户名"),
        (lambda c: setattr(c.server, "port", 70000), "端口"),
        (lambda c: setattr(c.monitor, "poll_interval_s", 1), "轮询间隔"),
        (lambda c: setattr(c.monitor, "threshold", 150), "百分比阈值"),
        (lambda c: setattr(c.monitor, "debounce_count", 0), "防抖"),
        (lambda c: setattr(c.monitor, "cooldown_s", -1), "冷却"),
        (lambda c: setattr(c.general, "log_level", "TRACE"), "日志级别"),
    ],
)
def test_validate_reports_errors(mutate, expected):
    cfg = AppConfig()
    cfg.server.host = "10.0.0.8"
    cfg.server.username = "ubuntu"
    mutate(cfg)
    errors = validate_config(cfg)
    assert any(expected in e for e in errors)


def test_validate_key_mode_requires_existing_key_file(tmp_path):
    cfg = AppConfig()
    cfg.server.host = "10.0.0.8"
    cfg.server.username = "ubuntu"
    cfg.server.auth_type = "key"
    cfg.server.key_path = str(tmp_path / "missing_key")
    assert any("私钥文件不存在" in e for e in validate_config(cfg))

    key = tmp_path / "id_ed25519"
    key.write_text("dummy", "utf-8")
    cfg.server.key_path = str(key)
    assert validate_config(cfg) == []


def test_validate_quiet_hours_equal_start_and_end():
    cfg = AppConfig()
    cfg.server.host = "10.0.0.8"
    cfg.server.username = "ubuntu"
    cfg.notify.quiet_hours.enabled = True
    cfg.notify.quiet_hours.start = "08:00"
    cfg.notify.quiet_hours.end = "08:00"
    assert any("免打扰" in e for e in validate_config(cfg))


def test_validate_free_mib_threshold_has_no_upper_bound():
    cfg = AppConfig()
    cfg.server.host = "10.0.0.8"
    cfg.server.username = "ubuntu"
    cfg.monitor.metric = "free_mib"
    cfg.monitor.threshold = 500_000
    assert validate_config(cfg) == []


def test_validate_free_mib_hysteresis_must_be_smaller_than_threshold():
    cfg = AppConfig()
    cfg.server.host = "10.0.0.8"
    cfg.server.username = "ubuntu"
    cfg.monitor.metric = "free_mib"
    cfg.monitor.threshold = 512
    cfg.monitor.hysteresis = 1024
    assert any("回差必须小于阈值" in e for e in validate_config(cfg))
