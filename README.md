# GpuWatch

**English** | [简体中文](README.zh-CN.md)

[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-0078D6?style=flat-square)](#requirements)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square)](#development)
[![License](https://img.shields.io/badge/license-MIT-2ea44f?style=flat-square)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/AIWfei/GpuWatch?style=flat-square)](https://github.com/AIWfei/GpuWatch/stargazers)

GpuWatch is a Windows tray app that watches NVIDIA GPU memory on remote Linux servers over SSH and notifies you when a GPU becomes available. It is built for shared GPU machines: stop SSHing in and re-running `nvidia-smi` just to see whether a card is free.

- **Zero server-side installation** — SSH and `nvidia-smi` are all it needs.
- **Runs quietly in the tray** — close the window and keep monitoring; optional start with Windows.
- **No telemetry** — no data leaves your machine except the SSH connection to your server; credentials stay in Windows Credential Manager.

![GpuWatch main window showing four idle GPUs and four busy GPUs](docs/screenshots/status.png)

> The application UI is currently in Simplified Chinese; the screenshots above use demo data. Localization contributions are welcome.
>
> Tab names used below: 状态 = Status, 连接 = Connection, 规则 = Rules, 通知与常规 = Notifications & General, 日志 = Logs.

## Features

- **Live GPU dashboard** — per-GPU memory used/total, usage bar, utilization, temperature and idle state, refreshed on your polling interval.
- **Idle rules that fit your workflow** — monitor used percent, used MiB or free MiB, with hysteresis, debounce, cooldown and optional repeat reminders.
- **Per-GPU or server-wide decisions** — evaluate each GPU independently, alert when any GPU is free, or only when all GPUs are free. Restrict monitoring to selected GPUs.
- **Secure SSH access** — password or OpenSSH/PEM private key (with optional passphrase), test connection, and strict SHA-256 host-key verification on first use.
- **Background resilience** — one reused SSH connection, exponential-backoff reconnects (5 s → 5 min), optional disconnect/recovery alerts, and no automatic retry after authentication or host-key failures.
- **Comfort features** — click a notification to open the window, optional sound, quiet hours, snooze for 30 min / 1 h / 2 h, close-to-tray, start with Windows and silent startup.
- **Operations** — rotating logs with in-app viewer and export, single-instance guard, `Ctrl+S` to save.

## Screenshots

<p align="center">
  <img src="docs/screenshots/rules.png" width="49%" alt="Idle rule configuration">
  <img src="docs/screenshots/notifications.png" width="49%" alt="Notification and startup settings">
</p>

## How it works

```text
Windows PC                                     Linux GPU server
┌───────────────────────────────┐              ┌──────────────────────────────┐
│ GpuWatch (PySide6 + paramiko) │──SSH────────▶│ nvidia-smi --query-gpu=...   │
│  UI · alert engine · tray     │              │ no agent, no daemon, no sudo │
└───────────────────────────────┘              └──────────────────────────────┘
```

GpuWatch keeps one SSH connection open and runs a read-only query on every poll:

```bash
LC_ALL=C timeout 15 nvidia-smi \
  --query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu,temperature.gpu \
  --format=csv,noheader,nounits
```

The CSV output is parsed locally; all threshold and notification logic runs on Windows. GPU probe errors are retried on the next poll, SSH connection failures use exponential backoff (5 s → 5 min), and authentication or host-key errors stop the monitor immediately.

## Requirements

| | Requirement |
| --- | --- |
| Client | Windows 10/11 (x64). |
| Server | Linux with an NVIDIA driver and `nvidia-smi`; tested on Ubuntu. The `timeout` command from coreutils is required. |
| Access | SSH reachability and a login account. Password or key authentication is supported; querying `nvidia-smi` does not require root. |
| From source | Python 3.11+ and [uv](https://docs.astral.sh/uv/). |
| Prebuilt binary | No Python installation needed. |

Non-interactive SSH sessions can have a different `PATH` than interactive shells. If `nvidia-smi` works in a terminal but GpuWatch reports exit code 127, set the full path (for example `/usr/bin/nvidia-smi`) under **Connection → Advanced**.

## Installation

### Option 1: Prebuilt Windows build

Download the latest Windows archive from [Releases](https://github.com/AIWfei/GpuWatch/releases), extract it anywhere, and run `GpuWatch.exe`. No Python installation is required. If no release is available yet, use either of the source options below.

### Option 2: Run from source

```powershell
git clone https://github.com/AIWfei/GpuWatch.git
cd GpuWatch
uv sync
uv run python -m gpuwatch
```

`uv run python run.py` is equivalent. To start hidden in the tray:

```powershell
uv run python -m gpuwatch --minimized
```

### Option 3: Build a standalone executable

```powershell
uv sync
uv run pyinstaller --noconfirm --clean gpuwatch.spec
```

The result is `dist/GpuWatch/GpuWatch.exe` (onedir, no console window). Distribute the whole `dist/GpuWatch/` directory as a zip. See [Building](#building-a-standalone-executable) for details.

## Quick start

1. **Connect** — open the **Connection** tab and fill in the server name, host, SSH port, username and authentication method. Click **Test connection** to verify access and list the detected GPUs.
2. **Verify the host key** — the first connection shows the server's SHA-256 fingerprint. Confirm it on the server with:
   ```bash
   ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
   ```
   Compare the value with the dialog, then choose **Trust and continue**. If the server key later changes, GpuWatch stops monitoring instead of connecting.
3. **Set the idle rule** — on the **Rules** tab choose the metric, threshold, hysteresis, debounce count, cooldown, GPU scope and aggregation. The preview at the bottom explains the resulting behavior in a sentence.
4. **Choose notifications** — on the **Notifications & General** tab enable desktop notifications and sound, configure quiet hours and disconnect alerts, and decide whether to start with Windows or close to the tray.
5. **Save and apply** — click **Save and apply** (or press `Ctrl+S`). Closing the window hides it to the tray by default. The tray menu can pause/resume monitoring, refresh immediately, snooze alerts, send a test notification or quit.

## Idle detection

Three metrics are available:

| Metric | Alert when | Considered busy again when |
| --- | --- | --- |
| Used memory (%) | used % < threshold | used % ≥ threshold + hysteresis |
| Used memory (MiB) | used MiB < threshold | used MiB ≥ threshold + hysteresis |
| Free memory (MiB) | free MiB ≥ threshold | free MiB < threshold − hysteresis |

- **Hysteresis** keeps a value near the threshold from flapping between idle and busy.
- **Debounce** requires the idle condition to hold for N consecutive samples before alerting.
- **Cooldown** prevents back-to-back alerts when a GPU briefly leaves and re-enters the idle state.
- **Repeat reminder** re-notifies at a fixed interval while the GPU stays idle.
- **Aggregation** — `Per GPU` evaluates and notifies for each card separately, `Any GPU` alerts if at least one selected GPU is idle, and `All GPUs` alerts only when every selected GPU is idle.
- **GPU scope** — monitor all GPUs or a selected subset.

With the defaults, a notification fires when the same GPU uses less than 20% of its memory for 3 consecutive samples (about 30 seconds at a 10-second interval); it is considered busy again at 25% or more. The cooldown is 10 minutes and repeat reminders are off by default.

## Security and privacy

- Passwords and private-key passphrases are stored only in **Windows Credential Manager** (service name `GpuWatch`). They are never written to `config.json` or the logs.
- Host keys are verified strictly. GpuWatch never uses `AutoAddPolicy`; the SHA-256 fingerprint must be confirmed on first connection, and a changed fingerprint stops monitoring.
- Authentication failures stop retries immediately, so repeated bad credentials cannot trip a fail2ban ban.
- The remote command is fixed and read-only. The configurable `nvidia-smi` path is shell-quoted with `shlex.quote`.
- GpuWatch sends no telemetry and contacts no third-party services; the only network connection is the SSH session to your server.
- Recommended: use a dedicated low-privilege account and key authentication. `nvidia-smi` queries do not require `sudo`.

## Data locations

| Item | Path |
| --- | --- |
| Configuration | `%APPDATA%\GpuWatch\config.json` |
| Trusted host keys | `%APPDATA%\GpuWatch\known_hosts` |
| Logs | `%APPDATA%\GpuWatch\logs\gpuwatch.log` (1 MB × 5 rotating files) |
| Credentials | Windows Credential Manager, service `GpuWatch`, accounts `<server_id>:password` / `<server_id>:passphrase` |

A corrupt configuration file is backed up as `config.json.bak` and defaults are restored automatically.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| “Cannot find `nvidia-smi`” (exit code 127) | The non-interactive SSH `PATH` does not include it. Set the full path under **Connection → Advanced**, e.g. `/usr/bin/nvidia-smi`. |
| “Unable to communicate with the NVIDIA driver” | The driver is not loaded, or the server was not rebooted after a driver upgrade. Check the driver on the server. |
| Authentication failed | Verify the same account and method with the `ssh` command. Some servers disable password authentication. |
| Private key cannot be read | PuTTY `.ppk` keys are not supported directly. Export an OpenSSH-format key with PuTTYgen. |
| No notifications | Turn off Focus Assist / Do Not Disturb, check Windows notification settings, and use **Send test notification**. |
| GpuWatch does not start with Windows | The executable was moved or blocked by security software. Re-enable autostart in the app and check **Settings → Apps → Startup**. |
| Frequent disconnects | NAT or firewalls may drop idle connections. GpuWatch sends SSH keepalives every 30 seconds; check the VPN or network path if the problem persists. |
| Host-key warning after reinstalling the server | The server key legitimately changed. Verify the new fingerprint on the server, then use **Clear trusted fingerprint** and reconnect. |

## Development

```powershell
git clone https://github.com/AIWfei/GpuWatch.git
cd GpuWatch
uv sync
uv run python -m gpuwatch
```

Run the test suite:

```powershell
uv run pytest
```

The tests cover `nvidia-smi` output parsing, the alert state machine, configuration handling and SSH host-key behavior. They do not require a Qt window, a network connection or a GPU.

For deeper implementation notes, see the [design document](GpuWatch%20%E5%BC%80%E5%8F%91%E6%96%87%E6%A1%A3.md) (Simplified Chinese).

### Building a standalone executable

```powershell
uv sync
uv run pyinstaller --noconfirm --clean gpuwatch.spec
```

The spec file bundles the icon, adds `src` to the import path and includes the keyring Windows backend. `onedir` is intentional: it starts faster and is less likely to trigger antivirus false positives than `onefile`. Test the build on a clean Windows machine without Python, including tray behavior, notifications, Credential Manager and SSH.

## Project structure

```text
src/gpuwatch/
  __main__.py       application entry point
  app.py            controller: wiring, lifecycle, config save, tray menu
  config.py         dataclasses, validation, atomic config I/O
  secrets_store.py  Windows Credential Manager wrapper
  ssh_session.py    SSH connection, host-key verification, reconnect backoff
  gpu_probe.py      nvidia-smi command construction and CSV parsing
  alert_engine.py   pure-logic idle state machine
  worker.py         QThread polling loop and test-connection task
  notifier.py       tray notifications, sound, quiet hours
  system.py         autostart, single instance, resource paths
  logging_setup.py  rotating file + in-app log handlers
  ui/               main window, tabs, dialogs
tests/              parser, alert engine, config and SSH unit tests
assets/             application icon
docs/screenshots/   README screenshots
gpuwatch.spec       PyInstaller build definition
```

## Contributing

Issues and pull requests are welcome — please read [CONTRIBUTING.md](CONTRIBUTING.md) first. The UI is currently Simplified Chinese; localization help is especially appreciated. Contributions are accepted under the MIT License.

## License

[MIT](LICENSE) © 2026 AIWfei. GpuWatch is not affiliated with or endorsed by NVIDIA.
