import asyncio
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Callable

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .config import redact


@asynccontextmanager
async def connect(url: str, timeout: float = 30):
    # 本地回环流量不走环境代理；连接、SSE、MCP 会话按相反顺序关闭。
    async with httpx.AsyncClient(trust_env=False, timeout=timeout) as http:
        async with streamable_http_client(url, http_client=http) as streams:
            async with ClientSession(*streams[:2], read_timeout_seconds=timedelta(seconds=timeout)) as session:
                await session.initialize()
                yield session


def debug_dump(label: str, data, output: Callable[[str], None] = print) -> None:
    output(redact(f"[debug] {label}: " + json.dumps(data, ensure_ascii=False, default=str)))


class ProgressLog:
    def __init__(self, output: Callable[[str], None] = print):
        self.output = output
        self.events: list[dict] = []
        self.done = asyncio.Event()

    async def callback(self, progress: float, total: float | None, message: str | None) -> None:
        self.events.append({"progress": progress, "total": total, "message": message})
        self.output(f"[进度 {progress:g}/{total:g}] {message}" if total is not None
                    else f"[进度 {progress:g}] {message}")
        if total is not None and progress >= total:
            self.done.set()

    async def wait_complete(self) -> None:
        # 真实传输中最后一条通知可能和最终结果同时到达，给回调一个完成窗口。
        await asyncio.wait_for(self.done.wait(), timeout=3)

