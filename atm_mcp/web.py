"""本地网页服务。浏览器只连接此服务，密钥和模型请求保留在 Python 服务端。"""
import argparse
import asyncio
import json
import time
from collections import OrderedDict
from dataclasses import asdict
from urllib.parse import urlparse

import uvicorn
from pydantic import BaseModel, ConfigDict, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .agent import RepairAgent, create_llm
from .bridge import ToolBridge
from .config import ROOT, Settings, DEFAULT_MCP_URL, redact
from .judge import JudgeRequest
from .transport import connect

CHAT_SESSIONS: OrderedDict = OrderedDict()


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(pattern=r"^[A-Za-z0-9-]{1,80}$")
    debug: bool = False


async def health(request: Request):
    try:
        settings = Settings.load()
        configured, model, url = True, settings.model, settings.mcp_url
    except ValueError:
        configured, model, url = False, "未配置", DEFAULT_MCP_URL
    try:
        async with connect(url, timeout=3) as session:
            tools = [tool.name for tool in (await session.list_tools()).tools]
        online = True
    except Exception:
        tools, online = [], False
    return JSONResponse({"mcp_online": online, "model_configured": configured,
                         "model": model, "tools": tools})


def event_stream(worker):
    async def stream():
        queue = asyncio.Queue(maxsize=100)

        async def emit(event, data):
            await queue.put((event, data))

        async def run():
            try:
                await worker(emit)
            except Exception as error:
                await emit("error", {"message": redact(str(error))})
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=10)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    return
                name, data = item
                yield f"event: {name}\ndata: {redact(json.dumps(data, ensure_ascii=False))}\n\n"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


async def read_payload(request, model):
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        raise ValueError("仅接受同源请求")
    raw = await request.body()
    if len(raw) > 60000:
        raise ValueError("输入过长")
    return model.model_validate_json(raw)


async def judge_route(request: Request):
    try:
        payload = await read_payload(request, JudgeRequest)
        settings = Settings.load()
    except Exception as error:
        return JSONResponse({"error": redact(str(error))}, status_code=400)

    async def worker(emit):
        started = time.perf_counter()
        async def progress(current, total, message):
            await emit("progress", {"progress": current, "total": total, "message": message})
        await emit("start", {"tool": "quick_judge"})
        async with connect(settings.mcp_url, timeout=settings.timeout + 10) as session:
            result = await session.call_tool("quick_judge", payload.model_dump(), progress_callback=progress)
            if result.isError:
                raise RuntimeError("; ".join(block.text for block in result.content if block.type == "text"))
            data = result.structuredContent
            if isinstance(data, dict) and "result" in data:
                data = data["result"]
            if not data:
                data = json.loads(next(block.text for block in result.content if block.type == "text"))
            data["end_to_end_ms"] = round((time.perf_counter() - started) * 1000)
            await emit("result", data)
    return event_stream(worker)


async def chat_route(request: Request):
    try:
        payload = await read_payload(request, ChatRequest)
        settings = Settings.load()
    except Exception as error:
        return JSONResponse({"error": redact(str(error))}, status_code=400)
    record = CHAT_SESSIONS.get(payload.session_id)
    if record and time.monotonic() - record["updated"] > 1800:
        CHAT_SESSIONS.pop(payload.session_id)
        record = None
    if record is None:
        if len(CHAT_SESSIONS) >= 100:
            inactive = next((key for key, value in CHAT_SESSIONS.items() if not value["lock"].locked()), None)
            if inactive is None:
                return JSONResponse({"error": "当前会话繁忙，请稍后重试"}, status_code=503)
            CHAT_SESSIONS.pop(inactive)
        record = {"messages": None, "updated": time.monotonic(), "lock": asyncio.Lock()}
        CHAT_SESSIONS[payload.session_id] = record
    if record["lock"].locked():
        return JSONResponse({"error": "上一条消息仍在处理中"}, status_code=409)

    async def worker(emit):
        async with record["lock"]:
            async def progress(current, total, message):
                await emit("progress", {"progress": current, "total": total, "message": message})
            def output(message):
                if payload.debug:
                    # 只有本次请求的调试信息会被发给发起请求的浏览器。
                    asyncio.create_task(emit("debug", {"message": redact(message)}))
            async with connect(settings.mcp_url) as session, create_llm(settings) as llm:
                bridge = await ToolBridge.discover(session, payload.debug, output)
                agent = RepairAgent(llm, bridge, settings)
                if record["messages"]:
                    agent.messages = record["messages"]
                try:
                    outcome = await agent.ask(payload.message, progress)
                    await emit("result", asdict(outcome))
                finally:
                    record["messages"] = agent.messages
                    record["updated"] = time.monotonic()
    return event_stream(worker)


app = Starlette(routes=[Route("/api/health", health),
    Route("/api/judge", judge_route, methods=["POST"]),
    Route("/api/chat", chat_route, methods=["POST"]),
    Mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")])


def main():
    parser = argparse.ArgumentParser(description="JUDGE 本地快速判断工作台")
    parser.add_argument("--port", type=int, default=8800)
    args = parser.parse_args()
    print(f"打开工作台：http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

