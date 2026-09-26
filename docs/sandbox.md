# Docker 沙箱

FloRaClaude 可将 Agent 的 `bash`、`read_file`、`write_file`、`list_dir` 放在 Docker 容器中执行。工作区在创建会话时固定，子 Agent 使用同一工作区和容器。工具调用仍经过现有的权限审批；批准调用不会改变沙箱模式。

## 启用

先安装并启动 Docker Engine 或 Docker Desktop，并确保 `docker` 命令可用。沙箱由 Docker 命令行驱动，不需要额外安装 Python `docker` 包。首次使用前拉取默认镜像：

```bash
docker pull python:3.12-alpine
```

在 `~/.flora/config.toml` 中设置：

```toml
[sandbox]
default_mode = "workspace_write" # off | read_only | workspace_write
image = "python:3.12-alpine"
```

也可以用 `FLORA_SANDBOX_DEFAULT_MODE` 和 `FLORA_SANDBOX_IMAGE` 覆盖。重启 `flora-core` 后，从项目目录运行 `flora chat` 或 `flora run`；这些命令把当前目录作为会话工作区，并使用配置的默认沙箱模式。

运行 `flora-tui` 时，启动界面会先让你选择工作区和沙箱模式。可以点击目录树中的文件夹，通过界面的 `Up` 和 `Go` 按钮导航，或在路径框中输入绝对目录路径；然后点击 `Off`、`Read only` 或 `Workspace write`，再点击 `Start chat`。确认前不会创建会话。也可以点击 `Start with defaults`，直接以启动 `flora-tui` 时的当前目录为工作区、以 `off` 模式开始。这两个 TUI 默认值不受 `sandbox.default_mode` 或 `FLORA_SANDBOX_DEFAULT_MODE` 影响。点击 `Cancel` 则退出启动选择，不创建会话。

客户端会显示会话实际生效的模式与目录。调用 `session.create` 或 `agent.run` 的其他客户端应传入绝对路径 `workspace_root` 和需要的 `sandbox_mode`。

## 模式与边界

| 模式 | 工作区挂载 | 用途 |
| --- | --- | --- |
| `read_only` | 只读 | 检查文件、运行不修改项目的命令 |
| `workspace_write` | 可写 | 修改项目文件 |
| `off` | 不启动容器 | 相对路径以所选工作区为起点，在宿主机执行 |

默认模式为 `off`，需要显式启用沙箱。`off` 模式下，所选工作区决定内置命令和文件工具的相对路径起点，但不限制绝对路径访问，Agent 仍可访问工作区外的宿主机文件。沙箱模式下，容器仅挂载会话工作区；根文件系统只读，运行时网络关闭，并设置 CPU、内存与进程数限制。沙箱会话不提供宿主机运行的 MCP 工具。Docker 不可用、镜像缺失或容器启动失败时，工具返回错误，不会在宿主机重试执行。

默认镜像提供 Python 3 和 `/bin/sh`，但不预装 `git`、`uv` 或 `bash`。如需额外工具，可构建包含 Python 3 和 `/bin/sh` 的镜像，设置 `sandbox.image` 后预先拉取。运行中的容器没有网络连接，因此不能依赖工具调用时在线安装软件。

`workspace_write` 允许 Agent 读取和改写工作区内的文件，包括 `.env`。如需保护项目内密钥，先将其移出挂载的工作区。`off` 模式以及 core 自身的宿主机进程不受容器隔离。
