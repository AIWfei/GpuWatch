from __future__ import annotations

import datetime as dt
import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

log = logging.getLogger(__name__)

APP_NAME = "GpuWatch"
APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
CONFIG_PATH = APP_DIR / "config.json"
KNOWN_HOSTS_PATH = APP_DIR / "known_hosts"
LOG_DIR = APP_DIR / "logs"
LOG_PATH = LOG_DIR / "gpuwatch.log"

SCHEMA_VERSION = 1

METRICS = ("used_percent", "used_mib", "free_mib")
AGGREGATES = ("per_gpu", "any", "all")
AUTH_TYPES = ("password", "key")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


@dataclass
class ServerCfg:
    id: str = "default"
    name: str = "GPU-Server"
    host: str = ""
    port: int = 22
    username: str = ""
    auth_type: str = "password"
    key_path: str = ""
    connect_timeout_s: int = 10
    nvidia_smi_path: str = "nvidia-smi"


@dataclass
class MonitorCfg:
    poll_interval_s: int = 10
    metric: str = "used_percent"
    threshold: float = 20
    hysteresis: float = 5
    debounce_count: int = 3
    cooldown_s: int = 600
    repeat_interval_s: int = 0
    aggregate: str = "per_gpu"
    gpu_filter: list[int] = field(default_factory=list)


@dataclass
class QuietHoursCfg:
    enabled: bool = False
    start: str = "23:00"
    end: str = "08:00"


@dataclass
class NotifyCfg:
    enabled: bool = True
    sound: bool = True
    duration_s: int = 10
    notify_on_busy_again: bool = False
    notify_on_disconnect: bool = True
    disconnect_after_failures: int = 3
    quiet_hours: QuietHoursCfg = field(default_factory=QuietHoursCfg)


@dataclass
class GeneralCfg:
    start_with_windows: bool = False
    start_minimized: bool = True
    close_to_tray: bool = True
    minimize_to_tray: bool = False
    auto_start_monitoring: bool = True
    log_level: str = "INFO"


@dataclass
class AppConfig:
    schema_version: int = SCHEMA_VERSION
    servers: list[ServerCfg] = field(default_factory=lambda: [ServerCfg()])
    monitor: MonitorCfg = field(default_factory=MonitorCfg)
    notify: NotifyCfg = field(default_factory=NotifyCfg)
    general: GeneralCfg = field(default_factory=GeneralCfg)

    @property
    def server(self) -> ServerCfg:
        return self.servers[0]


def _coerce_scalar(t: Any, value: Any) -> Any:
    if t is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        raise TypeError("expected bool")
    if t is int:
        if isinstance(value, bool):
            raise TypeError("expected int")
        return int(value)
    if t is float:
        if isinstance(value, bool):
            raise TypeError("expected float")
        return float(value)
    if t is str:
        if not isinstance(value, str):
            raise TypeError("expected str")
        return value
    return value


def _coerce_value(t: Any, value: Any) -> Any:
    if is_dataclass(t):
        if not isinstance(value, dict):
            raise TypeError(f"expected object for {t.__name__}")
        return from_dict(t, value)
    if get_origin(t) in (list, tuple):
        if not isinstance(value, list):
            raise TypeError("expected list")
        args = get_args(t)
        if not args:
            return list(value)
        return [_coerce_value(args[0], item) for item in value]
    return _coerce_scalar(t, value)


def from_dict(cls: type, data: dict) -> Any:
    if not isinstance(data, dict):
        raise TypeError("configuration root must be a JSON object")
    hints = get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        try:
            kwargs[f.name] = _coerce_value(hints[f.name], data[f.name])
        except (TypeError, ValueError):
            log.warning("ignoring invalid config field %s.%s", cls.__name__, f.name)
    return cls(**kwargs)


def normalize_config(cfg: AppConfig) -> AppConfig:
    if not cfg.servers:
        cfg.servers = [ServerCfg()]
    cfg.schema_version = SCHEMA_VERSION
    cfg.monitor.gpu_filter = sorted({int(i) for i in cfg.monitor.gpu_filter if int(i) >= 0})
    return cfg


def parse_time_str(value: str) -> dt.time:
    try:
        return dt.time.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"无效时间：{value!r}") from exc


def validate_config(cfg: AppConfig, check_key_file: bool = True) -> list[str]:
    errors: list[str] = []
    srv = cfg.server
    mon = cfg.monitor
    gen = cfg.general
    notify = cfg.notify

    if not srv.name.strip():
        errors.append("服务器名称不能为空")
    if not srv.host.strip():
        errors.append("服务器地址不能为空")
    if not 1 <= srv.port <= 65535:
        errors.append("SSH 端口必须在 1–65535 之间")
    if not srv.username.strip():
        errors.append("用户名不能为空")
    if srv.auth_type not in AUTH_TYPES:
        errors.append("认证方式无效")
    if not srv.nvidia_smi_path.strip():
        errors.append("nvidia-smi 路径不能为空")
    if not 1 <= srv.connect_timeout_s <= 120:
        errors.append("连接超时必须为 1–120 秒")
    if srv.auth_type == "key":
        if not srv.key_path.strip():
            errors.append("私钥模式下必须选择私钥文件")
        elif check_key_file and not Path(srv.key_path).expanduser().is_file():
            errors.append("私钥文件不存在")

    if not 5 <= mon.poll_interval_s <= 3600:
        errors.append("轮询间隔必须在 5–3600 秒之间")
    if mon.metric not in METRICS:
        errors.append("判定口径无效")
    if mon.aggregate not in AGGREGATES:
        errors.append("判定方式无效")
    if mon.threshold < 0:
        errors.append("阈值不能为负数")
    if mon.metric == "used_percent" and mon.threshold > 100:
        errors.append("百分比阈值必须在 0–100 之间")
    if mon.hysteresis < 0:
        errors.append("回差不能为负数")
    if mon.metric == "used_percent" and mon.hysteresis > 100:
        errors.append("百分比回差必须在 0–100 之间")
    if mon.metric == "free_mib" and mon.hysteresis >= mon.threshold:
        errors.append("空闲显存口径下，回差必须小于阈值")
    if mon.debounce_count < 1:
        errors.append("防抖次数至少为 1")
    if mon.cooldown_s < 0:
        errors.append("冷却时间不能为负数")
    if mon.repeat_interval_s < 0:
        errors.append("重复提醒间隔不能为负数")

    if notify.duration_s < 1:
        errors.append("通知停留时长至少为 1 秒")
    if notify.disconnect_after_failures < 1:
        errors.append("断线通知的连续失败次数至少为 1")
    if notify.quiet_hours.enabled:
        try:
            start = parse_time_str(notify.quiet_hours.start)
            end = parse_time_str(notify.quiet_hours.end)
            if start == end:
                errors.append("免打扰起止时间不能相同")
        except ValueError as exc:
            errors.append(str(exc))

    if gen.log_level not in LOG_LEVELS:
        errors.append("日志级别无效")
    return errors


def app_dir_for(config_path: Path) -> Path:
    return config_path.parent


class ConfigStore:
    def __init__(self, path: Path | None = None, known_hosts: Path | None = None):
        self.path = Path(path) if path else CONFIG_PATH
        self.known_hosts = Path(known_hosts) if known_hosts else (
            self.path.parent / "known_hosts" if path else KNOWN_HOSTS_PATH
        )

    def load(self) -> AppConfig:
        try:
            raw = self.path.read_text("utf-8")
        except FileNotFoundError:
            return AppConfig()
        except OSError:
            log.exception("failed to read config %s", self.path)
            return AppConfig()

        try:
            data = json.loads(raw)
            cfg = normalize_config(from_dict(AppConfig, data))
        except (ValueError, TypeError):
            log.exception("config %s is corrupt; backing up", self.path)
            self._backup_corrupt()
            return AppConfig()

        if cfg.schema_version > SCHEMA_VERSION:
            log.warning(
                "config schema %s is newer than supported %s; loading as-is",
                cfg.schema_version,
                SCHEMA_VERSION,
            )
        return cfg

    def save(self, cfg: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        payload = json.dumps(asdict(normalize_config(cfg)), ensure_ascii=False, indent=2)
        tmp.write_text(payload, "utf-8")
        os.replace(tmp, self.path)

    def _backup_corrupt(self) -> None:
        try:
            self.path.replace(self.path.with_name(self.path.name + ".bak"))
        except OSError:
            log.exception("failed to back up corrupt config")


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
