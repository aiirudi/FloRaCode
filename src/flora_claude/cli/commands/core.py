from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path

from flora_claude.core.config import FloRaConfig

_PID_FILE = Path.home() / ".flora" / "flora-core.pid"

# 尝试连接 daemon，成功则正常返回，失败则抛出 ConnectionRefusedError/OSError
async def _ping_check(config: FloRaConfig) -> None:
    _r, w =await asyncio.open_connection(config.host, config.port)
    w.close()
    await w.wait_closed()


# 读取 PID 文件并确认进程存活，进程已消失则删除文件返回 None
def _running_pid() -> int | None:
    if not _PID_FILE.exists():
        return None
    try:
        pid = int(_PID_FILE.read_text().strip())
        # 这里不是停止，而是用 0 检查对应进程是否存在，进程存在：正常返回；进程不存在：抛出 ProcessLookupError；没有权限：PermissionError。
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        # 清理失效 PID
        _PID_FILE.unlink(missing_ok=True)
        return None

def cmd_core_status(config:FloRaConfig) -> None:
    try:
        asyncio.run(_ping_check(config))
        print(f"running ({config.host}:{config.port})")
    except (ConnectionRefusedError, OSError):
        print("not running")

def cmd_core_start(config: FloRaConfig) -> None:
    try:
        asyncio.run(_ping_check(config))
        print(f"already runing ({config.host}:{config.port})")
        return 
    except (ConnectionRefusedError, OSError):
        pass

    proc = subprocess.Popen(
        [sys.executable, "-m", "flora_claude.core"],
        start_new_session=True,     #让子进程与当前  CLI 进程的生命周期分离
        stdout=subprocess.DEVNULL,  #丢弃daemon的标准输出
        stderr=subprocess.DEVNULL,  #丢弃daemon的错误输出
    )

    _PID_FILE.parent.mkdir(exist_ok=True, parents=True)
    _PID_FILE.write_text(str(proc.pid))
    print(f"started pid={proc.pid} ({config.host}:{config.port})")



def cmd_core_stop(config: FloRaConfig) -> None:
    pid = _running_pid()
    if pid is None:
        print("not running")
        return None

    os.kill(pid, signal.SIGTERM)
    _PID_FILE.unlink(missing_ok=True)
    print(f"stopped pid={pid}")