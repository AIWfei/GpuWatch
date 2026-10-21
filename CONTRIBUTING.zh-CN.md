# 参与贡献 GpuWatch

[English](CONTRIBUTING.md) | **简体中文**

感谢你愿意改进 GpuWatch。欢迎提交缺陷报告、文档修正、测试和功能建议。

## 开始之前

- 报告缺陷请开 GitHub Issue，并附上 Windows 版本、服务器发行版、GpuWatch 版本和相关日志。请先移除凭据、私钥和私有主机名。
- 较大的功能或重构，请先开 Issue 讨论方案，避免完成后无法合并。
- 安全问题请不要在公开 Issue 中披露细节，可通过维护者的 GitHub 主页私下联系，并留出修复时间。
- 小修复、错别字和文档更新可以直接提交 Pull Request。

## 开发环境

需要 Windows 10/11、Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。有一台带 NVIDIA GPU 的 Linux 机器便于集成测试，但开发和单元测试不需要它。

```powershell
git clone https://github.com/AIWfei/GpuWatch.git
cd GpuWatch
uv sync
uv run python -m gpuwatch
```

运行测试：

```powershell
uv run pytest
```

打包可执行文件：

```powershell
uv run pyinstaller --noconfirm --clean gpuwatch.spec
```

本程序以 Windows 为主要平台：开机自启使用注册表，凭据使用 Windows 凭据管理器，通知依赖系统托盘。修改平台相关代码时请留意这一点。

## 代码分布

- **纯逻辑**——`config.py`、`gpu_probe.py`、`alert_engine.py`、`ssh_session.py` 必须保持与 Qt 无关，可以在没有界面、网络和 GPU 的情况下测试。
- **依赖 Qt 的代码**——`worker.py`、`notifier.py`、`system.py` 和 `ui/`。网络 I/O 必须放在 Worker 线程，不能阻塞 UI 线程。
- **测试**——在 `tests/` 中为解析器、告警引擎和配置行为补充测试。使用抓取或构造的 `nvidia-smi` 输出，不要依赖真实 GPU。

更完整的实现说明见 [GpuWatch 开发文档.md](GpuWatch%20%E5%BC%80%E5%8F%91%E6%96%87%E6%A1%A3.md)。

## 测试要求

- 提交 Pull Request 前，所有测试必须通过：`uv run pytest`。
- 行为变化要补充或更新测试，尤其是阈值比较、回差、防抖、冷却和判定方式。
- 不要为了让测试通过而削弱主机密钥校验、凭据存储或重试限制。

涉及界面的改动，请手动检查：

1. 首次启动、测试连接和主机密钥确认对话框。
2. 保存、还原修改和校验错误提示。
3. 关闭到托盘、托盘菜单、点击通知的行为和单实例运行。
4. 免打扰时段、稍后提醒和发送测试通知。
5. 用 PyInstaller 打包，最好在干净的 Windows 机器上验收。

## 代码风格

- 与现有代码保持一致：4 空格缩进，公开函数加类型注解，只在意图不明显时写注释。
- 尽量不增加运行时依赖；如需新增，请先开 Issue 讨论。
- 界面文案暂时保持简体中文；本地化工作请先与维护者协调。
- 缺陷修复 PR 中不要夹带无关重构。

## 提交与 Pull Request

- 提交信息使用简短的祈使句标题，并在正文说明修改原因。
- 一个 Pull Request 只做一个逻辑改动。
- 界面改动请附截图或简短录屏。
- 行为、命令或配置发生变化时，同步更新 README 或开发文档。
- 提交贡献即表示你同意该贡献按项目的 [MIT 许可证](LICENSE) 授权。

Issue、讨论和 Pull Request 中使用英文或中文均可。
