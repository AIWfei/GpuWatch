# Contributing to GpuWatch

**English** | [简体中文](CONTRIBUTING.zh-CN.md)

Thanks for taking the time to improve GpuWatch. Bug reports, documentation fixes, tests and feature ideas are all welcome.

## Before you start

- For bug reports, open a GitHub Issue and include your Windows version, server distribution, GpuWatch version and the relevant log lines. Remove credentials and private hostnames first.
- For larger features or refactors, open an issue to discuss the approach before writing code. It avoids work that cannot be merged.
- For security issues, do not open a public issue with exploit details. Contact the maintainer privately through their GitHub profile and allow time for a fix.
- Small fixes, typo corrections and documentation updates can go straight to a pull request.

## Development setup

You need Windows 10/11, Python 3.11+ and [uv](https://docs.astral.sh/uv/). A Linux machine with an NVIDIA GPU is useful for integration testing but is not required for development or the unit tests.

```powershell
git clone https://github.com/AIWfei/GpuWatch.git
cd GpuWatch
uv sync
uv run python -m gpuwatch
```

Run the tests:

```powershell
uv run pytest
```

Build a standalone executable:

```powershell
uv run pyinstaller --noconfirm --clean gpuwatch.spec
```

The application is Windows-first: autostart uses the registry, credentials use the Windows Credential Manager, and notifications use the system tray. Please keep that in mind when changing platform-specific code.

## Where things live

- **Pure logic** — `config.py`, `gpu_probe.py`, `alert_engine.py` and `ssh_session.py` must stay independent of Qt and testable without a UI, network or GPU. This keeps the core easy to unit test.
- **Qt-dependent code** — `worker.py`, `notifier.py`, `system.py` and `ui/` may use Qt. Network I/O belongs on the worker thread, never on the UI thread.
- **Tests** — add tests in `tests/` for parser, alert-engine and configuration behavior. Use captured or synthetic `nvidia-smi` output rather than a real GPU.

A longer design document is available in [GpuWatch 开发文档.md](GpuWatch%20%E5%BC%80%E5%8F%91%E6%96%87%E6%A1%A3.md) (Simplified Chinese).

## Testing

- All tests must pass before a pull request is ready: `uv run pytest`.
- Add or update tests whenever behavior changes, especially around threshold comparisons, hysteresis, debounce, cooldown and aggregation.
- Do not weaken host-key verification, credential storage or retry limits to make a test pass.

For UI changes, also check manually:

1. First run, connection test and the host-key confirmation dialog.
2. Save, revert and validation errors.
3. Closing to tray, tray menu actions, notification click behavior and single-instance handling.
4. Quiet hours, snooze and test notification.
5. A PyInstaller build, preferably on a clean Windows machine.

## Style

- Match the existing code: 4-space indentation, type hints on public functions, and comments only where the intent is not obvious.
- Keep runtime dependencies minimal. Discuss new dependencies in an issue first.
- Keep user-facing UI text in Simplified Chinese for now; localization work should be coordinated with the maintainer.
- Avoid unrelated refactors in a bug-fix pull request.

## Commits and pull requests

- Use a short, imperative commit subject and explain the reason for the change in the body.
- Keep one logical change per pull request.
- Include screenshots or a short recording for UI changes.
- Update the README or the design document when behavior, commands or configuration change.
- By submitting a contribution, you agree that it is licensed under the project's [MIT License](LICENSE).

English and Chinese are both welcome in issues, discussions and pull requests.
