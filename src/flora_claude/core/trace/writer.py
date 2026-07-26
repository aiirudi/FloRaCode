from __future__ import annotations

import asyncio
from pathlib import Path

from flora_claude.core.trace.record import TraceRecord

class TraceWriter:
    # 初始化 TraceWriter, 写入目标路径在 start（） 函数前不会创建。只用调用 start（） 函数后才会对创建保存日志的文件路径 
    def __init__(self, path: Path) -> None:
        self._path = path
        self._queue: asyncio.Queue[TraceRecord] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    # 创建目录、后台启动 drain task
    async def start(self) -> None:
        self._path.parent.mkdir(exist_ok=True, parents=True)
        self._task = asyncio.create_task(self._drain())

    # 等待队列清空后取消drain task
    async def stop(self) -> None:
        await self._queue.join()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def emit(self, record: TraceRecord) -> None:
        self._queue.put_nowait(record)

    # 持续从队列读取 record 并追加写入文件 
    async def _drain(self) -> None:
        with open(self._path, "a") as f:
            while True:
                record = await self._queue.get()
                try:
                    f.write(record.model_dump_json() + "\n")
                    f.flush()
                finally:
                    self._queue.task_done()
