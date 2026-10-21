# GpuWatch 开发文档

Windows 桌面端 · 远程 Ubuntu / NVIDIA GPU 显存监控与空闲提醒　｜　v1.0　｜　2026-10-21

## 1. 项目概述

### 1.1 背景与目标

共享 GPU 服务器的显存经常被占满，想用卡时只能反复登录服务器执行 `nvidia-smi`。GpuWatch 是一个常驻 Windows 的带界面小工具：通过 SSH 定时读取远程 Ubuntu 服务器上 NVIDIA GPU 的显存使用情况，当使用量低于用户设定的阈值（即“有卡可用”）时，弹出 Windows 桌面通知。

### 1.2 核心特性

- **图形化配置**：SSH 连接、监控规则、通知方式、开机自启全部在界面设置，支持“测试连接”。
- **零部署**：服务器端无需安装任何程序，只依赖 SSH 与 `nvidia-smi`。
- **提醒不扰人**：连续多次采样满足才提醒（防抖）、回差、冷却时间、可选重复提醒。
- **常驻后台**：可最小化到任务栏，关闭窗口隐藏到系统托盘，支持开机自启并静默启动。
- **断线自愈**：断线后指数退避自动重连，可选“连接中断/恢复”通知。
- **安全**：密码存入 Windows 凭据管理器，严格校验服务器主机密钥。

### 1.3 前提假设

1. 服务器为 Ubuntu，已安装 NVIDIA 驱动，登录用户在 SSH 非交互会话中可执行 `nvidia-smi`（通常位于 `/usr/bin/nvidia-smi`）。
2. 本机为 Windows 10 / 11（x64），能直连服务器 SSH 端口（或已连 VPN）。
3. “最小化到任务栏”同时支持两种行为：点击最小化 → 窗口缩到任务栏（默认）；点击关闭 × → 隐藏到任务栏右下角的系统托盘并继续监控（默认）。“最小化时直接进托盘”做成可选项。无论哪种，监控都在后台线程运行，不受窗口状态影响。
4. “使用低于一定值”默认指显存占用百分比，同时支持“已用 MiB / 空闲 MiB”口径（见第 9 章）。

### 1.4 范围

| 类别 | 内容 |
| --- | --- |
| MVP（本文档实现） | 单台服务器；全部 NVIDIA GPU 的显存监控；阈值提醒；托盘；开机自启；打包 exe |
| 后续扩展 | 多服务器、跳板机、历史曲线、进程占用详情、Webhook/手机推送（见第 19 章） |

## 2. 需求规格

### 2.1 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| F1 | 配置 SSH：主机、端口、用户名、认证方式（密码 / 私钥+可选口令） | P0 |
| F2 | “测试连接”：验证认证并列出检测到的 GPU | P0 |
| F3 | 首次连接展示主机密钥指纹，用户确认后写入 known\_hosts；指纹变化时拒绝连接并警告 | P0 |
| F4 | 按设定间隔轮询每块 GPU 的显存（used/total）、利用率、温度 | P0 |
| F5 | 阈值规则：口径、阈值、回差、防抖次数、冷却、重复提醒 | P0 |
| F6 | GPU 范围（全部/指定）；判定方式（逐卡/任一/全部） | P1 |
| F7 | 桌面通知（点击通知唤起主窗口）、可选提示音 | P0 |
| F8 | 主界面实时显示每块 GPU 显存、状态与连接状态 | P0 |
| F9 | 托盘菜单：显示窗口、暂停/恢复监控、稍后提醒（贪睡）、测试通知、退出 | P0 |
| F10 | 开机自启（静默启动）、单实例运行 | P1 |
| F11 | 断线自动重连；连接中断/恢复通知 | P1 |
| F12 | 免打扰时段 | P2 |
| F13 | 日志查看与导出 | P1 |

### 2.2 非功能需求

- **性能**：空闲时 CPU 接近 0，内存 < 150 MB；UI 线程绝不阻塞在网络 IO 上。
- **可靠**：可连续运行数天；网络抖动、服务器重启后自动恢复；不泄漏连接和线程。
- **安全**：不明文保存密码；不关闭主机密钥校验；日志不含机密。
- **可维护**：核心逻辑（解析、告警状态机）为不依赖 Qt 的纯 Python，可单元测试。

## 3. 技术选型

| 层次 | 选型 | 理由 |
| --- | --- | --- |
| 语言 | Python 3.11+ | 开发快、生态完整，核心逻辑易测试 |
| GUI | PySide6（Qt 6） | 原生控件；自带 `QSystemTrayIcon`（托盘 + 通知）；信号槽天然适合跨线程通信 |
| SSH | paramiko ≥ 3.4 | 纯 Python；可非交互传入密码/私钥口令；支持 keepalive、自定义主机密钥策略 |
| 凭据 | keyring | 对接 Windows 凭据管理器 |
| 配置 | JSON + dataclass | 零依赖、可读、便于版本迁移 |
| 通知 | `QSystemTrayIcon.showMessage` | 无额外依赖，支持点击回调；可选升级为 windows-toasts |
| 打包 | PyInstaller（onedir）+ Inno Setup（可选） | 产出 exe / 安装包，用户无需安装 Python |
| 测试 | pytest（pytest-qt 可选） | 解析器、状态机、配置均可脱离界面测试 |

**方案对比说明**

- 不用系统自带 `ssh.exe`：无法非交互输入密码，主机密钥确认也是交互式的，进程管理繁琐。
- 不用 Electron / Tauri：逻辑很简单，Python 方案开发成本和体积更小。
- 不在服务器部署 DCGM / Prometheus exporter：需要服务器权限，违背“零部署”目标。
- 采集方式：SSH 执行 `nvidia-smi --query-gpu=...`，每次轮询新开一个 exec 通道，复用同一条 SSH 长连接。

## 4. 总体架构

### 4.1 架构图

```
+-------------------- Windows: GpuWatch process --------------------+
|  GUI thread (Qt main)            Monitor thread (QThread)         |
|  +-----------------+  signals   +-------------------------------+ |
|  | MainWindow      |<---------->| MonitorWorker                 | |
|  | TrayIcon        |            |  - SshSession (paramiko)      | |
|  | Notifier        |<-AlertEvent|  - GpuProbe (nvidia-smi)      | |
|  +--------+--------+            |  - AlertEngine (state machine)| |
|           |                     +---------------+---------------+ |
|     ConfigStore                                 | SSH (TCP 22)    |
|  config.json + Credential Manager               |                 |
+-------------------------------------------------+-----------------+
                                                  v
                          Ubuntu server: nvidia-smi --query-gpu=...
```

### 4.2 模块职责

| 模块 | 职责 | 依赖 Qt |
| --- | --- | --- |
| ConfigStore | 配置的读取、校验、原子写入、版本迁移 | 否 |
| SecretStore | 通过 keyring 读写密码/口令 | 否 |
| SshSession | 建立/复用 SSH 连接、执行远程命令、主机密钥校验 | 否 |
| GpuProbe | 构造 nvidia-smi 命令、解析输出为 `GpuSample` | 否 |
| AlertEngine | 阈值判定、防抖、回差、冷却、重复提醒，输出 `AlertEvent` | 否 |
| MonitorWorker | 轮询循环、重连退避、把结果以信号发给界面 | 是（QThread） |
| Notifier | 弹出通知、提示音、免打扰判断 | 是 |
| MainWindow / Tray | 配置界面、状态展示、托盘菜单 | 是 |
| system.py | 开机自启、单实例、数据目录 | 部分 |

### 4.3 数据流

1. 启动：单实例检查 → 加载配置 → 创建托盘 → 若 `auto_start_monitoring` 为真则启动 Worker。
2. 每个轮询周期：确保连接 → 执行 `nvidia-smi` → 解析 → 发出 `snapshot` 信号刷新界面 → `AlertEngine.feed()` 返回事件列表 → 发出 `alert` 信号 → Notifier 弹出通知。
3. 用户保存配置：写盘 → 停止旧 Worker → 用新配置启动新 Worker。

### 4.4 线程规则

- UI 线程只做界面；所有网络 IO 只发生在 Worker 线程或一次性的“测试连接”线程。
- 线程间只通过信号传递不可变数据（frozen dataclass / 列表拷贝），不共享可变对象。
- 停止 Worker 使用 `threading.Event`，睡眠用 `event.wait(interval)`，保证 `stop()` 能在一个网络超时内返回。

## 5. 项目结构

```
gpuwatch/
  requirements.txt
  gpuwatch.spec               # PyInstaller 配置
  assets/                     # icon.ico, tray_idle.png, tray_alert.png
  src/gpuwatch/
    __main__.py               # 入口：单实例 -> 加载配置 -> 启动 Qt
    app.py                    # 组装对象、托盘、信号连接
    config.py                 # 数据类 + ConfigStore
    secrets_store.py          # keyring 封装
    ssh_session.py            # SshSession / UnknownHostKeyError
    gpu_probe.py              # 命令构造、解析、GpuSample
    alert_engine.py           # 纯逻辑状态机
    worker.py                 # MonitorWorker(QThread)
    notifier.py               # 通知 + 提示音 + 免打扰
    system.py                 # 自启、单实例、路径
    logging_setup.py
    ui/
      main_window.py          # 标签页容器 + 关闭/最小化行为
      status_tab.py  connection_tab.py  rules_tab.py
      general_tab.py  log_tab.py  host_key_dialog.py
  tests/
    test_parser.py  test_alert_engine.py  test_config.py
```

## 6. 配置设计

### 6.1 存储位置

- 配置：`%APPDATA%\GpuWatch\config.json`
- 已信任主机密钥：`%APPDATA%\GpuWatch\known_hosts`
- 日志：`%APPDATA%\GpuWatch\logs\gpuwatch.log`（滚动，5 个 × 1 MB）
- 机密（密码、私钥口令）**不写入 JSON**，存入 Windows 凭据管理器：service = `GpuWatch`，用户名 = `<server.id>:password` 或 `<server.id>:passphrase`。

### 6.2 配置示例（schema\_version = 1）

```json
{
  "schema_version": 1,
  "servers": [{
    "id": "default", "name": "GPU-Server-1",
    "host": "10.0.0.8", "port": 22, "username": "ubuntu",
    "auth_type": "password", "key_path": "",
    "connect_timeout_s": 10, "nvidia_smi_path": "nvidia-smi"
  }],
  "monitor": {
    "poll_interval_s": 10, "metric": "used_percent", "threshold": 20,
    "hysteresis": 5, "debounce_count": 3, "cooldown_s": 600,
    "repeat_interval_s": 0, "aggregate": "per_gpu", "gpu_filter": []
  },
  "notify": {
    "enabled": true, "sound": true, "duration_s": 10,
    "notify_on_busy_again": false, "notify_on_disconnect": true,
    "disconnect_after_failures": 3,
    "quiet_hours": {"enabled": false, "start": "23:00", "end": "08:00"}
  },
  "general": {
    "start_with_windows": false, "start_minimized": true,
    "close_to_tray": true, "minimize_to_tray": false,
    "auto_start_monitoring": true, "log_level": "INFO"
  }
}
```

数据模型使用 `servers` 列表，MVP 界面只编辑第一项；将来支持多服务器时无需迁移配置。

### 6.3 字段说明

| 字段 | 含义 | 取值 / 默认 |
| --- | --- | --- |
| server.host / port | 服务器地址 / SSH 端口 | 必填 / 22 |
| server.auth\_type | 认证方式 | `password` 或 `key` |
| server.key\_path | 私钥文件路径（OpenSSH 或 PEM） | 仅 key 模式 |
| server.nvidia\_smi\_path | 远程命令 | `nvidia-smi`；找不到时填 `/usr/bin/nvidia-smi` |
| monitor.poll\_interval\_s | 轮询间隔（秒） | 10，范围 5–3600 |
| monitor.metric | 判定口径 | `used_percent`（已用 %，小于阈值）/ `used_mib`（已用 MiB，小于阈值）/ `free_mib`（空闲 MiB，大于等于阈值） |
| monitor.threshold | 阈值 | 随口径：0–100 或 MiB |
| monitor.hysteresis | 回差：越过“阈值 ± 回差”才视为重新变忙 | 5 |
| monitor.debounce\_count | 连续满足条件多少次才提醒 | 3 |
| monitor.cooldown\_s | 同一对象两次“空闲提醒”的最短间隔 | 600 |
| monitor.repeat\_interval\_s | 持续空闲时的重复提醒间隔，0 表示不重复 | 0 |
| monitor.aggregate | `per_gpu` 逐卡 / `any` 任一满足 / `all` 全部满足 | per\_gpu |
| monitor.gpu\_filter | 参与判定的 GPU index，空表示全部 | \[\] |
| general.close\_to\_tray | 点关闭 × 时隐藏到托盘而不是退出 | true |
| general.minimize\_to\_tray | 点最小化时直接隐藏到托盘（否则留在任务栏） | false |

### 6.4 配置读写代码

```python
# config.py（节选）
from __future__ import annotations
import json, os
from dataclasses import dataclass, field, asdict, fields, is_dataclass
from pathlib import Path
from typing import get_type_hints, get_origin, get_args

APP_NAME = 'GpuWatch'
APP_DIR = Path(os.environ.get('APPDATA', Path.home())) / APP_NAME
CONFIG_PATH = APP_DIR / 'config.json'

@dataclass
class ServerCfg:
    id: str = 'default'
    name: str = 'GPU-Server'
    host: str = ''
    port: int = 22
    username: str = ''
    auth_type: str = 'password'        # password | key
    key_path: str = ''
    connect_timeout_s: int = 10
    nvidia_smi_path: str = 'nvidia-smi'

@dataclass
class MonitorCfg:
    poll_interval_s: int = 10
    metric: str = 'used_percent'       # used_percent | used_mib | free_mib
    threshold: float = 20
    hysteresis: float = 5
    debounce_count: int = 3
    cooldown_s: int = 600
    repeat_interval_s: int = 0
    aggregate: str = 'per_gpu'         # per_gpu | any | all
    gpu_filter: list[int] = field(default_factory=list)

# QuietHours / NotifyCfg / GeneralCfg 同理，字段见 6.2

@dataclass
class AppConfig:
    schema_version: int = 1
    servers: list[ServerCfg] = field(default_factory=lambda: [ServerCfg()])
    monitor: MonitorCfg = field(default_factory=MonitorCfg)
    # notify: NotifyCfg, general: GeneralCfg

def from_dict(cls, data: dict):
    hints, kw = get_type_hints(cls), {}
    for f in fields(cls):
        if f.name not in data:
            continue                    # 缺失字段用默认值，向前兼容
        t, v = hints[f.name], data[f.name]
        if is_dataclass(t) and isinstance(v, dict):
            v = from_dict(t, v)
        elif get_origin(t) is list and is_dataclass(get_args(t)[0]):
            v = [from_dict(get_args(t)[0], x) for x in v]
        kw[f.name] = v
    return cls(**kw)

class ConfigStore:
    def load(self) -> AppConfig:
        try:
            return from_dict(AppConfig, json.loads(CONFIG_PATH.read_text('utf-8')))
        except FileNotFoundError:
            return AppConfig()
        except (ValueError, TypeError):  # JSON 损坏：备份后用默认值
            CONFIG_PATH.replace(CONFIG_PATH.with_suffix('.json.bak'))
            return AppConfig()

    def save(self, cfg: AppConfig) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix('.tmp')
        tmp.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), 'utf-8')
        os.replace(tmp, CONFIG_PATH)    # 原子替换，避免写一半断电损坏
```

### 6.5 机密存取与校验

```python
# secrets_store.py
import keyring
from keyring.errors import PasswordDeleteError

SERVICE = 'GpuWatch'

def get_secret(server_id: str, kind: str) -> str | None:     # kind: password | passphrase
    return keyring.get_password(SERVICE, f'{server_id}:{kind}')

def set_secret(server_id: str, kind: str, value: str) -> None:
    if value:
        keyring.set_password(SERVICE, f'{server_id}:{kind}', value)
    else:
        try:
            keyring.delete_password(SERVICE, f'{server_id}:{kind}')
        except PasswordDeleteError:
            pass
```

保存前校验：host 非空；port 1–65535；轮询间隔 5–3600；百分比阈值 0–100；`debounce_count ≥ 1`；key 模式下私钥文件存在；校验失败在界面字段旁标红提示，不允许保存。

## 7. SSH 连接模块

### 7.1 设计要点

- **长连接复用**：连接一次，之后每个周期只新开 exec 通道；连接异常才重连。
- **keepalive**：`transport.set_keepalive(30)`，防止 NAT / 防火墙回收空闲连接。
- **显式超时**：连接、banner、认证、命令执行都设置超时，避免线程永久卡死。
- **只用用户配置的认证方式**：`look_for_keys=False, allow_agent=False`，避免意外尝试其他密钥导致服务器因失败次数过多拒绝连接。
- **主机密钥**：使用独立的 known\_hosts 文件，策略为“未知即抛异常”，由界面弹窗确认后写入；不使用 `AutoAddPolicy`。

### 7.2 参考实现

```python
# ssh_session.py
from __future__ import annotations
import base64, hashlib
from dataclasses import dataclass
from pathlib import Path
import paramiko

class UnknownHostKeyError(Exception):
    def __init__(self, hostname: str, key: paramiko.PKey):
        super().__init__(f'unknown host key: {hostname}')
        self.hostname, self.key = hostname, key

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256(self.key.asbytes()).digest()
        return 'SHA256:' + base64.b64encode(digest).decode().rstrip('=')

class _RaiseOnUnknown(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        raise UnknownHostKeyError(hostname, key)

def trust_host_key(known_hosts: Path, err: UnknownHostKeyError) -> None:
    hk = paramiko.HostKeys()
    if known_hosts.exists():
        hk.load(str(known_hosts))
    hk.add(err.hostname, err.key.get_name(), err.key)   # 非 22 端口时 hostname 形如 [host]:port
    hk.save(str(known_hosts))

@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str

class SshSession:
    def __init__(self, server, get_secret, known_hosts: Path):
        self.s, self._secret, self._kh = server, get_secret, known_hosts
        self._client: paramiko.SSHClient | None = None

    def connect(self) -> None:
        self.close()
        self._kh.parent.mkdir(parents=True, exist_ok=True)
        self._kh.touch(exist_ok=True)
        c = paramiko.SSHClient()
        c.load_host_keys(str(self._kh))
        c.set_missing_host_key_policy(_RaiseOnUnknown())
        t = self.s.connect_timeout_s
        kw = dict(hostname=self.s.host, port=self.s.port, username=self.s.username,
                  timeout=t, banner_timeout=t, auth_timeout=t,
                  look_for_keys=False, allow_agent=False)
        if self.s.auth_type == 'password':
            kw['password'] = self._secret('password')
        else:
            kw['key_filename'] = self.s.key_path
            kw['passphrase'] = self._secret('passphrase') or None
        try:
            c.connect(**kw)
        except BaseException:
            c.close()
            raise
        c.get_transport().set_keepalive(30)
        self._client = c

    def is_alive(self) -> bool:
        t = self._client.get_transport() if self._client else None
        return bool(t and t.is_active())

    def exec(self, cmd: str, timeout: float = 20) -> ExecResult:
        if not self.is_alive():
            raise ConnectionError('ssh session is not connected')
        _, out, err = self._client.exec_command(cmd, timeout=timeout)
        o = out.read().decode('utf-8', 'replace')
        e = err.read().decode('utf-8', 'replace')
        return ExecResult(out.channel.recv_exit_status(), o, e)

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
```

### 7.3 首次连接的主机密钥信任流程

1. 连接抛出 `UnknownHostKeyError` → 界面弹出对话框，显示主机、密钥算法（`key.get_name()`）和 SHA256 指纹。
2. 用户点“信任并继续” → 调用 `trust_host_key()` 写入 known\_hosts → 重新连接。用户可在服务器上执行 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` 核对指纹。
3. 之后若指纹与记录不符，paramiko 抛 `BadHostKeyException`：立即停止重试并红色警告“服务器指纹已变化（可能是服务器重装或中间人攻击）”，用户必须在设置页点“清除已信任指纹”后重新确认。

### 7.4 异常分类与处理

`AuthenticationException` 与 `BadHostKeyException` 都是 `SSHException` 的子类，`except` 时必须先捕获具体异常、再捕获 `SSHException`。

| 异常 | 含义 | 处理 |
| --- | --- | --- |
| `socket.timeout` / `OSError`（含 `NoValidConnectionsError`）/ `EOFError` / 其他 `SSHException` | 网络或会话问题 | 状态“重连中”，指数退避重试 |
| `AuthenticationException` | 用户名/密码/私钥错误 | 停止自动重试；状态“认证失败”；通知一次 |
| `BadHostKeyException` | 主机密钥变化 | 停止重试；高优先级警告 |
| `UnknownHostKeyError` | 主机未被信任 | 停止；等待用户在弹窗中确认 |
| `ProbeError`（见第 8 章） | nvidia-smi 执行或解析失败 | 保持连接；状态“采样失败”；连续失败 N 次后通知 |

### 7.5 重连退避

```python
class Backoff:   # 放在 ssh_session.py 中，供 worker.py 导入
    STEPS = (5, 10, 20, 40, 80, 160, 300)     # 秒，封顶 5 分钟
    def __init__(self): self.n = 0
    def next(self) -> int:
        d = self.STEPS[min(self.n, len(self.STEPS) - 1)]
        self.n += 1
        return d
    def reset(self): self.n = 0                # 连接并采样成功后复位
```

跳板机（P2）：先连接跳板机，再 `jump.get_transport().open_channel('direct-tcpip', (target_host, target_port), (jump_host, 0))`，把返回的 channel 作为 `sock=` 参数传给目标机的 `connect()`。

## 8. GPU 数据采集与解析

### 8.1 远程命令

```
LC_ALL=C timeout 15 nvidia-smi --query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader,nounits
```

- `noheader,nounits`：只输出纯数字（显存单位 MiB，利用率 %，温度 ℃），便于解析。
- `LC_ALL=C`：固定输出格式，不受服务器语言环境影响。
- `timeout 15`：GPU 或驱动异常时 `nvidia-smi` 偶尔会卡死，由服务器端兜底，超时返回码 124。
- `nvidia_smi_path` 经 `shlex.quote` 后拼接，用户填写带空格的路径也安全。

输出样例（每块 GPU 一行）：

```
0, GPU-3f0a9c1e-xxxx, NVIDIA GeForce RTX 4090, 1043, 24564, 3, 41
1, GPU-7b21d5aa-xxxx, NVIDIA GeForce RTX 4090, 22816, 24564, 97, 68
```

### 8.2 参考实现

```python
# gpu_probe.py
from __future__ import annotations
import csv, io, shlex
from dataclasses import dataclass

FIELDS = 'index,uuid,name,memory.used,memory.total,utilization.gpu,temperature.gpu'

class ProbeError(Exception):
    pass

@dataclass(frozen=True)
class GpuSample:
    index: int
    uuid: str
    name: str
    mem_used_mib: int | None
    mem_total_mib: int | None
    util_percent: int | None
    temp_c: int | None

    @property
    def used_percent(self) -> float | None:
        if self.mem_used_mib is None or not self.mem_total_mib:
            return None
        return self.mem_used_mib * 100 / self.mem_total_mib

    @property
    def free_mib(self) -> int | None:
        if self.mem_used_mib is None or self.mem_total_mib is None:
            return None
        return self.mem_total_mib - self.mem_used_mib

def build_command(smi_path: str = 'nvidia-smi') -> str:
    return (f'LC_ALL=C timeout 15 {shlex.quote(smi_path)} '
            f'--query-gpu={FIELDS} --format=csv,noheader,nounits')

def _int(s: str) -> int | None:
    try:
        return int(float(s))
    except ValueError:
        return None                      # [N/A] / [Not Supported]

def parse_query_output(text: str) -> list[GpuSample]:
    out = []
    for row in csv.reader(io.StringIO(text), skipinitialspace=True):
        if len(row) < 7 or not row[0].strip().isdigit():
            continue                     # 忽略 .bashrc 等混入的杂行
        used, total, util, temp = (_int(x) for x in row[-4:])
        name = ','.join(row[2:-4]).strip()   # 兼容名称中含逗号
        out.append(GpuSample(int(row[0]), row[1].strip(), name, used, total, util, temp))
    if not out:
        raise ProbeError('无法解析 nvidia-smi 输出: ' + text[:200])
    return out

def describe_failure(code: int, stderr: str, stdout: str) -> str:
    lines = (stderr or stdout).strip().splitlines()
    first = lines[0] if lines else ''
    if code == 127:
        return '服务器上找不到 nvidia-smi，请在连接设置中填写完整路径'
    if code == 124:
        return 'nvidia-smi 执行超时（GPU 或驱动可能异常）'
    return f'nvidia-smi 退出码 {code}: {first}'

def query_gpus(ssh, server) -> list[GpuSample]:
    r = ssh.exec(build_command(server.nvidia_smi_path), timeout=20)
    if r.exit_code != 0:
        raise ProbeError(describe_failure(r.exit_code, r.stderr, r.stdout))
    return parse_query_output(r.stdout)
```

### 8.3 边界情况

| 情况 | 处理 |
| --- | --- |
| 字段为 `[N/A]` / `[Not Supported]` | 解析为 None；界面显示 N/A；该卡不参与判定 |
| 多块 GPU | 每行一块；界面用 index 标识，uuid 作为内部唯一键 |
| 显存口径 | `memory.used` 是整卡已分配显存，包含所有用户和容器内的进程；空载时驱动也会占几十 MiB，阈值不要设为 0 |
| MIG 模式 | 本版本不支持 MIG 实例级监控，GPU 级字段若为 N/A 按第一条处理 |
| 登录脚本在非交互模式下输出内容 | 解析器只接受“第一列为整数且至少 7 列”的行，其余忽略 |
| 找不到命令 / 驱动异常 | 返回码 127 / 非 0，转成 `ProbeError` 并把服务器报错的第一行展示给用户 |

## 9. 告警引擎

告警引擎是纯逻辑模块：输入“某一时刻的 GPU 采样 + 当前时间”，输出“需要通知的事件列表”。它不依赖 Qt、网络和系统时钟（时间由调用方传入），所以可以完整单元测试。

### 9.1 判定口径

| metric | 判定“空闲”的条件 | 示例 |
| --- | --- | --- |
| `used_percent` | 已用 % < 阈值 | 阈值 20：显存占用低于 20% 时提醒 |
| `used_mib` | 已用 MiB < 阈值 | 阈值 2048：已用低于 2 GiB 时提醒 |
| `free_mib` | 空闲 MiB ≥ 阈值 | 阈值 20480：至少 20 GiB 可用时提醒（常用于“我要跑这个任务需要多少显存”） |

- `aggregate = per_gpu`：每块 GPU 一个独立状态机（key 为 `gpu:0`、`gpu:1`…）。
- `aggregate = any`：只有一个状态机（key 为 `server`），任意一块被选中的 GPU 空闲即视为空闲。
- `aggregate = all`：只有一个状态机，所有被选中的 GPU 都空闲才视为空闲。
- 回差用来防止数值在阈值附近抖动：空闲状态下，只有越过“阈值 + 回差”（`free_mib` 为“阈值 − 回差”）才算重新变忙。

### 9.2 状态机

```
          idle N times in a row AND cooldown passed
   +------+ ----------------------------------------> +------+
   | BUSY |                                           | IDLE |   emit IDLE
   +------+ <---------------------------------------- +------+   emit REMIND every repeat_interval
          value crosses threshold +/- hysteresis
          (emit BUSY_AGAIN if enabled)
```

- BUSY 下：本次满足条件则连续计数 +1，否则清零；计数达到 `debounce_count` 且距上次提醒已超过 `cooldown_s` 才进入 IDLE 并发出事件。冷却未到时保持 BUSY，冷却一到若仍空闲就会补发。
- IDLE 下：越过回差 → 回到 BUSY；仍空闲且 `repeat_interval_s > 0` 且间隔已到 → 发 REMIND；处于阈值与回差之间的“灰区”→ 保持不变、不通知。

### 9.3 时序示例

参数：轮询 10 s，阈值 20%，回差 5，防抖 3 次，冷却 600 s。

| 时刻 | 显存占用 | 计数 | 状态 | 事件 |
| --- | --- | --- | --- | --- |
| 0 s | 80% | 0 | BUSY | 无 |
| 10 s | 15% | 1 | BUSY | 无 |
| 20 s | 15% | 2 | BUSY | 无 |
| 30 s | 15% | 3 | IDLE | **IDLE 事件（弹通知）** |
| 40 s | 22% | — | IDLE | 无（处于 20–25 的灰区） |
| 50 s | 30% | 0 | BUSY | 无（可选 BUSY\_AGAIN） |
| 60–90 s | 10% 连续 3 次 | 3 | BUSY | 无，距上次提醒不足 600 s，等冷却结束后补发 |

### 9.4 参考实现

```python
# alert_engine.py（纯逻辑，不依赖 Qt）
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass
from enum import Enum

class Kind(str, Enum):
    IDLE = 'idle'                # 刚变空闲
    REMIND = 'remind'            # 持续空闲的重复提醒
    BUSY_AGAIN = 'busy'          # 重新变忙
    DISCONNECT = 'disconnect'    # 连接中断
    RECOVER = 'recover'          # 连接恢复
    ERROR = 'error'              # 认证失败等致命错误

@dataclass(frozen=True)
class AlertEvent:
    kind: Kind
    key: str                     # gpu:0 / server / conn
    title: str
    message: str

def in_quiet_hours(q, now: dt.time | None = None) -> bool:
    if not q.enabled:
        return False
    now = now or dt.datetime.now().time()
    s, e = dt.time.fromisoformat(q.start), dt.time.fromisoformat(q.end)
    return s <= now < e if s <= e else (now >= s or now < e)   # 支持跨午夜

@dataclass
class _State:
    status: str = 'busy'         # busy | idle
    streak: int = 0
    last_notify: float | None = None

class AlertEngine:
    def __init__(self, mon, notify_busy_again: bool, server_name: str):
        self.mon, self.busy_again, self.name = mon, notify_busy_again, server_name
        self._st: dict[str, _State] = {}

    def reset(self) -> None:
        self._st.clear()

    def _value(self, s):
        return {'used_percent': s.used_percent, 'used_mib': s.mem_used_mib,
                'free_mib': s.free_mib}[self.mon.metric]

    def _classify(self, v: float) -> tuple[bool, bool]:
        """返回 (是否空闲, 是否已越过回差确认变忙)"""
        t, h = self.mon.threshold, self.mon.hysteresis
        if self.mon.metric == 'free_mib':        # 越大越空闲
            return v >= t, v < t - h
        return v < t, v >= t + h                 # 越小越空闲

    def feed(self, samples, now: float) -> list[AlertEvent]:
        f = self.mon.gpu_filter
        picked = [s for s in samples
                  if (not f or s.index in f) and s.mem_used_mib is not None and s.mem_total_mib]
        flags = [self._classify(self._value(s)) for s in picked]
        events: list[AlertEvent] = []
        if self.mon.aggregate == 'per_gpu':
            for s, (idle, rel) in zip(picked, flags):
                events += self._step(f'gpu:{s.index}', idle, rel, now, [s])
        elif picked:
            idle_samples = [s for s, fl in zip(picked, flags) if fl[0]] or picked
            if self.mon.aggregate == 'any':
                idle, rel = any(fl[0] for fl in flags), all(fl[1] for fl in flags)
            else:                                # all
                idle, rel = all(fl[0] for fl in flags), any(fl[1] for fl in flags)
            events += self._step('server', idle, rel, now, idle_samples)
        return events

    def _step(self, key, idle, released, now, samples) -> list[AlertEvent]:
        st, m, ev = self._st.setdefault(key, _State()), self.mon, []
        if st.status == 'busy':
            st.streak = st.streak + 1 if idle else 0
            cooled = st.last_notify is None or now - st.last_notify >= m.cooldown_s
            if st.streak >= m.debounce_count and cooled:
                st.status, st.last_notify = 'idle', now
                ev.append(self._event(Kind.IDLE, key, samples))
        else:
            if released:
                st.status, st.streak = 'busy', 0
                if self.busy_again:
                    ev.append(self._event(Kind.BUSY_AGAIN, key, samples))
            elif idle and m.repeat_interval_s > 0 and now - st.last_notify >= m.repeat_interval_s:
                st.last_notify = now
                ev.append(self._event(Kind.REMIND, key, samples))
        return ev

    def _event(self, kind: Kind, key: str, samples) -> AlertEvent:
        def fmt(s):
            return (f'GPU {s.index} {s.name}：{s.mem_used_mib / 1024:.1f}/'
                    f'{s.mem_total_mib / 1024:.1f} GiB（{s.used_percent:.0f}%）')
        body = '\n'.join(fmt(s) for s in samples[:4])      # Windows 通知正文有长度上限
        if len(samples) > 4:
            body += f'\n…等共 {len(samples)} 张'
        title = {Kind.IDLE: f'{self.name} 有空闲显存',
                 Kind.REMIND: f'{self.name} 显存仍然空闲',
                 Kind.BUSY_AGAIN: f'{self.name} 显存已被占用'}[kind]
        return AlertEvent(kind, key, title, body)
```

### 9.5 暂停、稍后提醒与免打扰

- **暂停监控**：Worker 不采样、不判定，状态显示“已暂停”。
- **稍后提醒（贪睡 N 分钟）**与**免打扰时段**：Worker 继续采样并刷新界面，但跳过 `engine.feed()`。结束后状态机从当前状态继续，若此时仍然空闲会补发提醒，不会因为错过窗口而漏报。
- 连接类通知（中断、认证失败等）不受贪睡和免打扰影响，因为它们代表监控本身已失效。

## 10. 监控 Worker

### 10.1 职责与信号

Worker 是一个 `QThread` 子类，在后台循环：确保连接 → 采样 → 发信号。它自己不碰任何控件。

| 信号 | 载荷 | 用途 |
| --- | --- | --- |
| `snapshot` | `list[GpuSample]` | 刷新状态页的 GPU 表格 |
| `status` | `(code, 文本)` | 连接状态栏与托盘提示；code 取值：connecting / connected / reconnecting / probe\_error / auth\_failed / host\_key\_changed / host\_key\_unknown / paused / stopped / error |
| `alert` | `AlertEvent` | 交给 Notifier 弹通知 |
| `host_key_unknown` | `UnknownHostKeyError` | 界面弹出指纹确认对话框 |

向 UI 暴露的线程安全方法：`stop()`、`pause(bool)`、`snooze(minutes)`、`poll_now()`。

### 10.2 参考实现

```python
# worker.py
from __future__ import annotations
import logging, threading, time
import paramiko
from PySide6.QtCore import QThread, Signal
from .alert_engine import AlertEngine, AlertEvent, Kind, in_quiet_hours
from .gpu_probe import ProbeError, query_gpus
from .ssh_session import SshSession, UnknownHostKeyError, Backoff

log = logging.getLogger(__name__)

class MonitorWorker(QThread):
    snapshot = Signal(object)
    status = Signal(str, str)
    alert = Signal(object)
    host_key_unknown = Signal(object)

    def __init__(self, cfg, get_secret, known_hosts, parent=None):
        super().__init__(parent)
        self.cfg, self.srv = cfg, cfg.servers[0]
        self.ssh = SshSession(self.srv, get_secret, known_hosts)
        self.engine = AlertEngine(cfg.monitor, cfg.notify.notify_on_busy_again, self.srv.name)
        self._stopping, self._paused = False, False
        self._wake = threading.Event()
        self._snooze_until = 0.0
        self._backoff, self._fails, self._down_notified = Backoff(), 0, False

    # ---------- 供 UI 线程调用 ----------
    def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        self.ssh.close()                 # 打断可能阻塞中的网络调用
        self.wait(3000)

    def pause(self, on: bool) -> None:
        self._paused = on
        self._wake.set()

    def snooze(self, minutes: int) -> None:
        self._snooze_until = time.monotonic() + minutes * 60

    def poll_now(self) -> None:
        self._wake.set()

    # ---------- 线程主体 ----------
    def run(self) -> None:
        while not self._stopping:
            wait = self.cfg.monitor.poll_interval_s
            if self._paused:
                self.status.emit('paused', '监控已暂停')
            else:
                try:
                    self._tick()
                except UnknownHostKeyError as e:
                    self.host_key_unknown.emit(e)
                    self.status.emit('host_key_unknown', '主机密钥未信任，等待确认')
                    return
                except paramiko.BadHostKeyException:
                    self._fatal('host_key_changed', '服务器主机密钥已变化，已停止连接（可能存在中间人攻击）')
                    return
                except paramiko.AuthenticationException:
                    self._fatal('auth_failed', '认证失败，请检查用户名、密码或私钥')
                    return
                except ProbeError as e:
                    self._on_failure('probe_error', str(e))
                except (OSError, EOFError, paramiko.SSHException) as e:
                    if self._stopping:
                        break
                    self.ssh.close()
                    wait = self._backoff.next()
                    self._on_failure('reconnecting', f'连接失败：{e}，{wait} 秒后重试')
                except Exception:
                    log.exception('unexpected error in worker')
                    wait = 30
                    self.status.emit('error', '内部错误，详见日志')
            self._wake.wait(wait)
            self._wake.clear()
        self.ssh.close()
        self.status.emit('stopped', '已停止')

    def _tick(self) -> None:
        if not self.ssh.is_alive():
            self.status.emit('connecting', '正在连接…')
            self.ssh.connect()
        samples = query_gpus(self.ssh, self.srv)
        self._on_success()
        self.snapshot.emit(samples)
        now = time.monotonic()
        if now < self._snooze_until or in_quiet_hours(self.cfg.notify.quiet_hours):
            return
        for ev in self.engine.feed(samples, now):
            self.alert.emit(ev)

    def _on_success(self) -> None:
        self._backoff.reset()
        if self._down_notified and self.cfg.notify.notify_on_disconnect:
            self.alert.emit(AlertEvent(Kind.RECOVER, 'conn', f'{self.srv.name} 连接已恢复', '监控恢复正常'))
        self._fails, self._down_notified = 0, False
        self.status.emit('connected', '已连接')

    def _on_failure(self, code: str, text: str) -> None:
        self._fails += 1
        self.status.emit(code, text)
        n = self.cfg.notify
        if n.notify_on_disconnect and self._fails >= n.disconnect_after_failures and not self._down_notified:
            self._down_notified = True
            self.alert.emit(AlertEvent(Kind.DISCONNECT, 'conn', f'{self.srv.name} 连接中断', text))

    def _fatal(self, code: str, text: str) -> None:
        self.status.emit(code, text)
        self.alert.emit(AlertEvent(Kind.ERROR, 'fatal', f'{self.srv.name} 监控已停止', text))
```

要点：

- `except` 的顺序不能调换：`AuthenticationException`、`BadHostKeyException` 是 `SSHException` 的子类，必须排在通用的 `SSHException` 之前；`UnknownHostKeyError` 是普通 `Exception`，必须排在最后的 `except Exception` 之前。
- `stop()` 先置标志、唤醒睡眠、再主动关闭 SSH 连接，这样即使 Worker 正阻塞在网络读写上，也能在很短时间内退出，窗口关闭不会卡住。
- `snapshot` 在 `_on_success` 之后发出，因此界面上“最后更新时间”始终代表一次成功采样。

### 10.3 配置变更与“测试连接”

- 保存配置后，由 `app.py` 调用 `old.stop()`，再用新配置创建并启动新的 Worker，重新连接所有信号。逻辑简单，且新旧配置不会混用。
- “测试连接”使用一次性线程，读取的是界面上**尚未保存**的表单值（密码框有输入就用输入值，否则回退到凭据管理器）：

```python
class TestConnectionTask(QThread):
    ok = Signal(object)               # list[GpuSample]，用于填充“指定 GPU”复选框
    failed = Signal(str)
    unknown_host = Signal(object)

    def __init__(self, server, get_secret, known_hosts):
        super().__init__()
        self.server, self.get_secret, self.kh = server, get_secret, known_hosts

    def run(self):
        ssh = SshSession(self.server, self.get_secret, self.kh)
        try:
            ssh.connect()
            self.ok.emit(query_gpus(ssh, self.server))
        except UnknownHostKeyError as e:
            self.unknown_host.emit(e)
        except paramiko.AuthenticationException:
            self.failed.emit('认证失败：用户名、密码或私钥不正确')
        except paramiko.BadHostKeyException:
            self.failed.emit('主机密钥与已信任记录不一致')
        except ProbeError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(f'连接失败：{e}')
        finally:
            ssh.close()
```

## 11. 通知模块

### 11.1 方案

默认使用 Qt 自带的 `QSystemTrayIcon.showMessage()`：无需额外依赖，在 Windows 10/11 上表现为系统 Toast 通知，并且支持 `messageClicked` 信号（点击通知唤起主窗口）。需要按钮或常驻通知时，再升级为 `windows-toasts` 之类的原生 Toast 库（见 19 章）。

### 11.2 参考实现

```python
# notifier.py
from __future__ import annotations
import winsound
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from .alert_engine import AlertEvent, Kind

_MI = QSystemTrayIcon.MessageIcon
_ICON = {Kind.DISCONNECT: _MI.Warning, Kind.ERROR: _MI.Critical}   # 其余用 Information

class Notifier:
    def __init__(self, tray: QSystemTrayIcon, get_cfg, main_window):
        self.tray, self.get_cfg, self.win = tray, get_cfg, main_window   # get_cfg() -> NotifyCfg

    def show(self, ev: AlertEvent, force: bool = False) -> None:
        cfg = self.get_cfg()
        if not cfg.enabled and not force:
            return
        icon = _ICON.get(ev.kind, _MI.Information)
        self.tray.showMessage(ev.title[:63], (ev.message or ' ')[:255], icon, cfg.duration_s * 1000)
        if cfg.sound:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        if ev.kind in (Kind.IDLE, Kind.REMIND):
            QApplication.alert(self.win, 0)          # 任务栏图标闪烁，直到窗口被激活
```

“发送测试通知”调用 `show(AlertEvent(Kind.IDLE, 'test', 'GpuWatch 测试通知', '看到这条消息说明通知功能正常'), force=True)`。

### 11.3 Windows 平台注意事项

1. 托盘图标必须已经 `show()` 才能弹通知；启动时用 `QSystemTrayIcon.isSystemTrayAvailable()` 检查，不可用则在日志和界面中提示。
2. Windows 10/11 会忽略 `showMessage` 的超时参数，停留时长由系统“辅助功能”设置决定；通知同时会进入操作中心保留。因此 `duration_s` 仅作参考。
3. 标题限 63 字符、正文限 255 字符（Win32 限制），代码里提前截断；多卡时正文最多列 4 张。
4. 系统开启“专注助手 / 勿扰”时通知不弹出、只进操作中心。界面“通知”区需放一句提示，并提供“发送测试通知”按钮帮助用户排查（设置 → 系统 → 通知）。
5. 用 `python.exe` 直接运行时通知来源显示为 Python；打包成 exe 后显示应用名与图标。
6. 若同时听到系统通知声和 `MessageBeep` 两次声音，关闭 `sound` 选项，由系统通知声音设置接管。
7. 点击通知：`tray.messageClicked.connect(window.show_and_raise)`。

## 12. 界面设计

### 12.1 主窗口布局

主窗口为固定的 5 个标签页：状态、连接、规则、通知与常规、日志。下面是“状态”页示意：

```
+----------------------------------------------------------------------+
| GpuWatch                                                  _   []  X  |
+----------------------------------------------------------------------+
| [Status] [Connection] [Rules] [Notify & General] [Log]               |
+----------------------------------------------------------------------+
| Server: GPU-Server-1 (10.0.0.8)        State: (green) Connected      |
| Last update 14:03:25   Next poll in 7s  [Refresh] [Pause] [Snooze v] |
|                                                                      |
| GPU | Name       | Memory used/total | Used % bar   | Util | Temp | State |
|  0  | RTX 4090   | 1.0 / 24.0 GiB    | [#.........]  4% |  3% | 41C | IDLE  |
|  1  | RTX 4090   | 22.3 / 24.0 GiB   | [#########.] 93% | 97% | 68C | BUSY  |
|                                                                      |
| Rule: used % < 20, 3 times in a row (about 30 s)                     |
+----------------------------------------------------------------------+
| Status bar: connected - saved settings applied                       |
+----------------------------------------------------------------------+
```

### 12.2 各标签页控件与配置项

| 标签页 | 控件 | 对应配置 |
| --- | --- | --- |
| 状态 | 只读表格（GPU、名称、显存、占用条、利用率、温度、状态）；连接状态灯；最后更新时间；按钮“立即刷新”“暂停/恢复”“稍后提醒 ▾（30 分钟 / 1 小时 / 2 小时 / 取消）” | 无（只展示） |
| 连接 | 服务器名称、主机、端口、用户名；认证方式单选（密码 / 私钥）；密码框（已保存时占位“已保存，留空表示不修改”）；私钥路径 + 浏览按钮；私钥口令；高级：nvidia-smi 路径、连接超时；按钮“测试连接”“清除已信任指纹” | `servers[0].*` + 凭据管理器 |
| 规则 | 轮询间隔；判定口径下拉；阈值（单位随口径切换为 % 或 MiB）；回差；防抖次数；冷却时间；重复提醒（复选框 + 间隔）；判定方式（逐卡 / 任一 / 全部）；GPU 范围（全部，或勾选具体卡，列表来自最近一次测试/采样）；底部一句话实时预览 | `monitor.*` |
| 通知与常规 | 启用通知、提示音、断线通知（含连续失败次数）、重新变忙通知、免打扰（开关 + 起止时间）；开机自启、自启时静默启动、关闭按钮行为、最小化行为、启动后自动开始监控；日志级别；“发送测试通知” | `notify.*`、`general.*` |
| 日志 | 只读文本框（最多 2000 行），按钮“打开日志目录”“清空”“导出” | 无 |

规则页底部的预览句示例：“当 GPU 显存占用低于 20%，连续 3 次采样（约 30 秒）后提醒；回升到 25% 以上视为重新变忙；同一块卡 10 分钟内不重复提醒。”参数一改就实时刷新，让用户一眼确认设置符合预期。

### 12.3 系统托盘

托盘右键菜单：

- 显示主窗口（双击托盘图标同效）
- 暂停 / 恢复监控
- 立即刷新
- 稍后提醒 ▸ 30 分钟 / 1 小时 / 2 小时 / 取消
- 发送测试通知
- 退出

托盘图标按状态切换：绿色（正常）、灰色（暂停或未连接）、红色（认证失败等错误）、带角标（当前有空闲 GPU，用户打开窗口后清除）。悬停提示示例：“GpuWatch：已连接，2 张 GPU，最低占用 4%”。

### 12.4 窗口行为

```python
# ui/main_window.py（节选）
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QMainWindow, QSystemTrayIcon

class MainWindow(QMainWindow):
    def __init__(self, get_cfg, tray):
        super().__init__()
        self.get_cfg, self.tray = get_cfg, tray
        self.quitting = False                  # 托盘“退出”时置 True
        self._tip_shown = False

    def changeEvent(self, e):                  # 点最小化：可选直接隐藏到托盘
        if (e.type() == QEvent.Type.WindowStateChange and self.isMinimized()
                and self.get_cfg().general.minimize_to_tray):
            QTimer.singleShot(0, self.hide)
        super().changeEvent(e)

    def closeEvent(self, e):                   # 点 ×：隐藏而不是退出
        if self.get_cfg().general.close_to_tray and not self.quitting:
            e.ignore()
            self.hide()
            if not self._tip_shown:
                self._tip_shown = True
                self.tray.showMessage('GpuWatch 仍在后台运行', '右键托盘图标可退出程序',
                                      QSystemTrayIcon.MessageIcon.Information, 5000)
        else:
            e.accept()

    def show_and_raise(self):
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()
```

`QApplication.setQuitOnLastWindowClosed(False)` 必须设置，否则最后一个窗口隐藏后进程会退出。真正退出的流程：`window.quitting = True` → `worker.stop()` → `tray.hide()` → `app.quit()`。

### 12.5 交互细节

- 点“保存”：校验 → 写 `config.json` → 写凭据管理器 → 重启 Worker → 状态栏提示“已保存并应用”；有未保存修改时标签页标题加 \*。
- “测试连接”：按钮禁用并显示忙碌状态；成功后列出检测到的 GPU，并刷新规则页的 GPU 勾选列表；失败显示 7.4 节中的人话错误。
- 状态页：占用低于阈值的行标绿并显示“空闲”，否则显示“忙碌”；连接异常时顶部显示彩色横幅和“去修改连接设置”按钮。
- 首次启动（尚未填写主机）：自动显示窗口并定位到“连接”页。
- 界面文字集中放在一处，便于以后做多语言；Qt 6 默认支持高 DPI，无需额外设置。

## 13. 系统集成与启动流程

### 13.1 开机自启

写入当前用户的 Run 注册表项，无需管理员权限；用户也可在 Windows“设置 → 应用 → 启动”中看到并开关。

```python
# system.py（节选）
import sys, winreg
from pathlib import Path

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'

def _command(minimized: bool) -> str:
    flag = ' --minimized' if minimized else ''
    if getattr(sys, 'frozen', False):                      # 打包后的 exe
        return f'"{sys.executable}"{flag}'
    pyw = Path(sys.executable).with_name('pythonw.exe')    # 开发环境：无控制台窗口
    return f'"{pyw}" -m gpuwatch{flag}'

def set_autostart(enabled: bool, minimized: bool = True, name: str = 'GpuWatch') -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, _command(minimized))
        else:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass

def is_autostart(name: str = 'GpuWatch') -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, name)
            return True
    except FileNotFoundError:
        return False
```

每次启动时若自启项已启用，重新写入一次，以应对用户移动了 exe 位置。

### 13.2 单实例

用 `QLocalServer` / `QLocalSocket`：第二个实例启动时连上第一个实例并发送一条消息，第一个实例收到后把窗口置前，第二个实例随即退出。

```python
from PySide6.QtNetwork import QLocalServer, QLocalSocket

KEY = 'GpuWatch-single-instance'

def acquire_single_instance(on_activate):
    sock = QLocalSocket()
    sock.connectToServer(KEY)
    if sock.waitForConnected(300):               # 已有实例在运行：通知它显示窗口
        sock.write(b'show')
        sock.flush()
        sock.waitForBytesWritten(300)
        return None
    QLocalServer.removeServer(KEY)               # 清理上次异常退出遗留的残留
    server = QLocalServer()
    server.newConnection.connect(lambda: (server.nextPendingConnection(), on_activate()))
    server.listen(KEY)
    return server                                # 调用方必须持有引用，防止被回收
```

### 13.3 启动流程（`__main__.py`）

```python
def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)          # 关窗口不退出进程
    win_ref = []
    guard = acquire_single_instance(lambda: win_ref and win_ref[0].show_and_raise())
    if guard is None:
        return 0                                   # 已有实例，本进程直接退出
    setup_logging()
    store = ConfigStore()
    cfg = store.load()
    ctrl = AppController(app, store, cfg)         # 组装托盘 / 窗口 / 通知 / Worker
    win_ref.append(ctrl.window)
    first_run = not cfg.servers[0].host
    if first_run or '--minimized' not in sys.argv:
        ctrl.window.show()                         # 手动启动显示窗口；自启时只留托盘
    if cfg.general.auto_start_monitoring and not first_run:
        ctrl.start_worker()
    return app.exec()
```

`AppController`（`app.py`）负责对象组装与信号连接：

```python
from functools import partial

def start_worker(self):
    if self.worker:
        self.worker.stop()
    srv = self.cfg.servers[0]
    w = MonitorWorker(self.cfg, partial(get_secret, srv.id), KNOWN_HOSTS)   # get_secret(kind)
    w.snapshot.connect(self.window.status_tab.on_snapshot)
    w.status.connect(self.on_status)               # 更新状态栏、托盘图标与提示
    w.alert.connect(self.notifier.show)
    w.host_key_unknown.connect(self.on_unknown_host)
    w.start()
    self.worker = w

def on_unknown_host(self, err):
    dlg = HostKeyDialog(err.hostname, err.key.get_name(), err.fingerprint, self.window)
    if dlg.exec():                                 # 用户点“信任并继续”
        trust_host_key(KNOWN_HOSTS, err)
        self.start_worker()
```

### 13.4 日志

```python
import logging
from logging.handlers import RotatingFileHandler

def setup_logging(level: str = 'INFO') -> None:
    log_dir = APP_DIR / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(log_dir / 'gpuwatch.log', maxBytes=1_000_000,
                            backupCount=5, encoding='utf-8')
    h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(h)
    logging.getLogger('paramiko').setLevel(logging.WARNING)
```

- 打包为 windowed 程序后 `sys.stderr` 为 None，不要添加 `StreamHandler`。
- 日志页通过自定义 `logging.Handler` 发 Qt 信号追加文本，不要在非 UI 线程直接操作控件。
- 日志内容：连接/断开、重连次数、采样失败原因、触发的告警事件。绝不记录密码、口令。

## 14. 安全设计

- **凭据**：密码和私钥口令只存 Windows 凭据管理器（按当前登录用户保护）；`config.json` 里没有任何机密。
- **主机密钥**：不使用 `AutoAddPolicy`；首次连接需用户确认指纹，指纹变化则拒绝连接。
- **认证优先级**：推荐使用私钥；使用密码时建议为监控专门建一个低权限只读账户（`nvidia-smi` 查询不需要 sudo）。
- **防止触发封禁**：认证失败后立即停止自动重试（见 7.4），避免服务器上的 fail2ban 等机制把本机 IP 封掉。
- **远程命令固定**：只执行拼好的 `nvidia-smi` 查询命令，路径经 `shlex.quote`，没有任何由远程输出反向控制本机的逻辑。
- **无遥测**：程序不向任何第三方发送数据。
- **供应链**：依赖版本固定在 `requirements.txt`，发版前升级 paramiko、cryptography 的安全补丁；有条件的话给 exe 做代码签名，减少 SmartScreen 警告。

## 15. 错误处理与状态提示

| 场景 | 状态码 | 界面 / 托盘表现 | 通知策略 |
| --- | --- | --- | --- |
| 正常 | connected | 绿灯 | 无 |
| 连接中 / 重连中 | connecting / reconnecting | 黄灯，显示下次重试秒数 | 连续失败达到设定次数后发一次“连接中断”，恢复时发一次“已恢复” |
| 认证失败 | auth\_failed | 红灯，状态页顶部红色横幅 + “去修改连接设置” | 通知一次，停止重试 |
| 主机密钥变化 | host\_key\_changed | 红灯 + 安全警告 | 通知一次，停止重试 |
| 主机未信任 | host\_key\_unknown | 弹出指纹确认对话框 | 无 |
| nvidia-smi 失败 / 解析失败 | probe\_error | 橙灯 + 具体原因 | 连续失败达到设定次数后通知一次 |
| 已暂停 | paused | 灰灯 | 无 |
| 内部异常 | error | 红灯，提示查看日志 | 无，30 秒后继续尝试 |

本机睡眠或网络切换后，原 SSH 连接通常已经失效：下一次 `exec` 会抛异常，由退避重连自动恢复，MVP 不需要额外处理。后续可监听系统唤醒事件，唤醒后立即复位退避并 `poll_now()`，缩短恢复时间。

## 16. 打包与发布

### 16.1 开发环境

```
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m gpuwatch
```

`requirements.txt`（发版前用 `pip freeze` 固定为精确版本）：

```
PySide6>=6.6
paramiko>=3.4
keyring>=25.0
pyinstaller>=6.0    # 仅构建期
pytest>=8.0         # 仅测试
```

### 16.2 PyInstaller 打包

`__main__.py` 使用了包内相对导入，PyInstaller 不能直接把它当脚本入口。在仓库根目录增加一个启动脚本 `run.py`：

```python
# run.py
import sys
from gpuwatch.__main__ import main

if __name__ == '__main__':
    sys.exit(main())
```

构建命令（默认 onedir，不要用 onefile）：

```
pyinstaller --noconfirm --windowed --name GpuWatch --icon assets/icon.ico --paths src --hidden-import keyring.backends.Windows --add-data "assets;assets" run.py
```

- **为什么选 onedir**：启动更快，不需要每次解压到临时目录，被杀毒软件误报的概率也更低。
- `--windowed`：不显示控制台窗口；此时 `sys.stdout / sys.stderr` 为 None，代码里不能直接 `print`，日志只写文件。
- `--hidden-import keyring.backends.Windows`：keyring 通过动态方式加载后端，不显式声明时打包后会找不到 Windows 凭据后端。
- 资源文件（图标等）统一通过下面的函数定位，开发环境和打包环境都可用：

```python
def resource_path(rel: str) -> Path:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
    return base / rel
```

### 16.3 分发

- 最简单：把 `dist/GpuWatch/` 整个目录压缩成 zip，解压即用。
- 更正式：用 Inno Setup 制作安装包，创建开始菜单快捷方式；在 `[Registry]` 段为开机自启项加上 `uninsdeletevalue` 标志，卸载时自动清除。
- 打包后务必在**没有安装 Python 的干净 Windows 机器或虚拟机**上验收：托盘、通知、凭据管理器、自启、SSH 连接都要走一遍。
- 版本号采用语义化版本，写在 `__version__` 中并显示在“关于”里；MVP 阶段手动下载更新。

## 17. 测试方案

### 17.1 单元测试（无需 Qt、网络、GPU）

| 文件 | 覆盖点 |
| --- | --- |
| `test_parser.py` | 单卡 / 多卡；含 `[N/A]`；名称含逗号；混入杂行；空输出报错；返回码 127 / 124 的提示 |
| `test_alert_engine.py` | 防抖；回差灰区；冷却后补发；重复提醒；`any` / `all` 聚合；`free_mib` 口径；`gpu_filter`；跨午夜免打扰 |
| `test_config.py` | 缺字段补默认；未知字段忽略；坏 JSON 备份后恢复默认；保存后再读取一致 |

告警引擎测试示例（把 9.3 的时序表直接变成用例）：

```python
from types import SimpleNamespace as NS
from gpuwatch.alert_engine import AlertEngine, Kind
from gpuwatch.gpu_probe import GpuSample

def sample(used_pct, total=24000):
    return GpuSample(0, 'u', 'RTX', int(total * used_pct / 100), total, 0, 40)

def make(**kw):
    mon = NS(metric='used_percent', threshold=20, hysteresis=5, debounce_count=3,
             cooldown_s=600, repeat_interval_s=0, aggregate='per_gpu', gpu_filter=[])
    mon.__dict__.update(kw)
    return AlertEngine(mon, False, 'srv')

def test_idle_after_three_consecutive_samples():
    eng, kinds = make(), []
    for i, pct in enumerate((80, 15, 15, 15, 22, 30)):    # 每 10 秒一次采样
        kinds += [e.kind for e in eng.feed([sample(pct)], i * 10)]
    assert kinds == [Kind.IDLE]      # 22% 处于灰区，不发；30% 变忙，不发

def test_cooldown_delays_second_notification():
    eng, fired = make(), []
    seq = [15, 15, 15, 30] + [15] * 70
    for i, pct in enumerate(seq):
        for e in eng.feed([sample(pct)], i * 10):
            fired.append((i * 10, e.kind))
    assert fired[0] == (20, Kind.IDLE)
    assert fired[1][0] == 620        # 距上次提醒满 600 秒后补发
```

### 17.2 集成测试：用“假 nvidia-smi”模拟显存变化

不需要真实 GPU。在一台 Ubuntu（WSL2、Hyper-V 或 VirtualBox 虚拟机均可，需运行 sshd）上放一个假的 `nvidia-smi`，让它直接输出一个可随时修改的文件：

```
# /usr/local/bin/nvidia-smi（测试用，chmod +x）
#!/bin/bash
cat /tmp/fake_gpu.csv

# 模拟显存被占满 / 释放
echo '0, GPU-fake, Fake GPU, 22000, 24000, 95, 70' > /tmp/fake_gpu.csv
echo '0, GPU-fake, Fake GPU, 500, 24000, 1, 30'    > /tmp/fake_gpu.csv
```

在“连接”页把 `nvidia_smi_path` 指向这个脚本，就可以反复演练：触发提醒、冷却、回差、重复提醒、断线重连（停掉 sshd）、认证失败（改密码）、指纹变化（重新生成服务器主机密钥）。

### 17.3 手工验收清单

| 编号 | 验收项 | 期望 |
| --- | --- | --- |
| T1 | 首次连接 | 弹出指纹确认；信任后连接成功并列出 GPU |
| T2 | 密码错误 | 红灯；只通知一次；不再重试 |
| T3 | 服务器主机密钥变化 | 拒绝连接并给出安全警告 |
| T4 | 断网 / 服务器重启 | 自动重连；通知“连接中断”和“已恢复”各一次 |
| T5 | 显存降到阈值以下 | 连续 N 次后弹通知；点击通知唤起主窗口 |
| T6 | 防抖、冷却、回差、重复提醒 | 与 9 章一致 |
| T7 | 贪睡与免打扰 | 期间无通知；结束后若仍空闲则补发 |
| T8 | 窗口行为 | 最小化留在任务栏；× 隐藏到托盘；托盘“退出”才真正退出 |
| T9 | 自启与单实例 | 开机静默启动到托盘；重复双击 exe 只会唤起已有窗口 |
| T10 | 睡眠唤醒 | 唤醒后能自动恢复监控 |
| T11 | 长时间运行 | 连续 24 小时以上，内存与句柄数稳定 |
| T12 | 干净机器 | 打包产物在无 Python 的 Windows 上完整可用 |

## 18. 里程碑与工作量

以下为单人、熟悉 Python 与 Qt 的粗略估算：

| 阶段 | 内容 | 验收产出 | 预估 |
| --- | --- | --- | --- |
| M1 核心链路 | config、ssh\_session、gpu\_probe；先写成命令行脚本 | 终端能打印远程 GPU 显存 | 1 天 |
| M2 告警引擎 | alert\_engine + 单元测试 | 状态机用例全部通过 | 1 天 |
| M3 最小界面 | 主窗口（连接 / 规则 / 状态页）、Worker、托盘、通知 | 能配置并收到桌面通知 | 2 天 |
| M4 功能完善 | 主机密钥弹窗、测试连接、日志页、贪睡 / 免打扰、自启、单实例 | 功能完整 | 2 天 |
| M5 打包验收 | PyInstaller、图标、干净机器验收、README | 可分发的 exe | 1 天 |

合计约 7 个工作日。建议严格按 M1 → M5 顺序推进：先用命令行把“采集 + 判定”跑通，再套界面，调试成本最低。

## 19. 后续扩展

- **多服务器**：数据模型已是 `servers` 列表，每台服务器一个 Worker，界面增加服务器列表即可。
- **更多连接方式**：跳板机（ProxyJump）、读取 `~/.ssh/config`（`paramiko.SSHConfig`）、ssh-agent / Pageant 认证。
- **流式采集**：长连接执行 `nvidia-smi ... -l 5` 并逐行读取，降低服务器上频繁拉起进程的开销。
- **进程级信息**：`nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv`，通知中附上占用者（注意权限与容器 PID 命名空间问题）。
- **历史曲线**：SQLite 存储 + pyqtgraph 绘图。
- **更多通知渠道**：Webhook（企业微信、钉钉、飞书、Slack）、Bark / ntfy 手机推送。
- **原生 Toast**：`windows-toasts` 等库，支持“稍后提醒”按钮和常驻通知（需要固定 AppUserModelID）。
- **系统事件**：监听睡眠唤醒、网络切换，立即重连。
- **其他**：AMD（`rocm-smi`）支持、多语言、自动更新。

## 附录 A：服务器端自检命令

```
# 1. 确认驱动与命令可用
nvidia-smi
which nvidia-smi

# 2. 用与程序完全相同的方式（非交互）执行，在 Windows PowerShell 中运行
ssh user@host 'LC_ALL=C timeout 15 nvidia-smi --query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader,nounits'

# 3. 在服务器上查看主机密钥指纹，用来核对首次连接弹窗里的 SHA256 指纹
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

## 附录 B：常见问题

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| 提示找不到 nvidia-smi（退出码 127） | 非交互 SSH 会话的 PATH 不含其所在目录 | 在“连接”页高级选项填完整路径，如 `/usr/bin/nvidia-smi` |
| 提示无法与 NVIDIA 驱动通信 | 驱动未加载，或升级驱动后服务器未重启 | 在服务器上排查驱动 |
| 认证失败 | 密码错误、账户被禁用、服务器禁止密码登录 | 先用命令行 `ssh` 验证同样的账号能否登录 |
| 私钥无法读取 | PuTTY 的 `.ppk` 格式不被 paramiko 直接支持 | 用 PuTTYgen 导出为 OpenSSH 格式私钥 |
| 通知不弹出 | 专注助手 / 勿扰、系统通知被关闭 | 设置 → 系统 → 通知；用“发送测试通知”排查 |
| 开机自启不生效 | exe 被移动，或被安全软件拦截 | 在程序中重新勾选自启；检查“设置 → 应用 → 启动” |
| 连接频繁断开 | NAT / 防火墙回收空闲连接 | 已内置 30 秒 keepalive，必要时调小 |
