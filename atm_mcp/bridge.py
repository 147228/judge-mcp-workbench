import copy
import json

from jsonschema import Draft202012Validator, ValidationError
from mcp import ClientSession

from .config import redact
from .domain import ProgressCallback
from .transport import debug_dump


class ToolBridge:
    def __init__(self, session: ClientSession, tools: list, debug: bool = False, output=print):
        self.session, self.debug, self.output = session, debug, output
        self.catalog = {tool.name: tool for tool in tools if tool.name == "atm_repair"}
        if "atm_repair" not in self.catalog:
            raise ValueError("MCP 服务端未暴露 atm_repair")
        self.call_count = 0
        self.openai_tools = []
        for tool in self.catalog.values():
            schema = copy.deepcopy(tool.inputSchema)
            schema["additionalProperties"] = False
            self.openai_tools.append({"type": "function", "function": {
                "name": tool.name, "description": tool.description or "",
                "parameters": schema,
            }})
        if debug:
            debug_dump("list_tools -> OpenAI tools", self.openai_tools, output)

    @classmethod
    async def discover(cls, session: ClientSession, debug: bool = False, output=print):
        tools, cursor, seen = [], None, set()
        while True:
            page = await session.list_tools(cursor=cursor)
            tools.extend(page.tools)
            cursor = page.nextCursor
            if not cursor:
                break
            if cursor in seen:
                raise RuntimeError("list_tools 返回重复分页游标")
            seen.add(cursor)
        return cls(session, tools, debug, output)

    async def execute(self, name: str, arguments: str, progress: ProgressCallback | None = None) -> dict:
        if name not in self.catalog:
            return {"ok": False, "error": "未知或未获允许的工具"}
        try:
            args = json.loads(arguments)
            schema = next(t["function"]["parameters"] for t in self.openai_tools
                          if t["function"]["name"] == name)
            Draft202012Validator(schema).validate(args)
        except (ValueError, ValidationError) as error:
            return {"ok": False, "error": redact(f"参数不合法，请补充或更正：{error}")}
        self.call_count += 1
        try:
            result = await self.session.call_tool(name, args, progress_callback=progress)
        except Exception as error:
            # 创建工单是有副作用的调用；连接失败时不自动重试，避免重复创建。
            return {"ok": False, "error": redact(f"MCP 调用失败：{error}"),
                    "note": "结果未确认，可能已经建单；请核查服务端，不要自动重试。"}
        if self.debug:
            debug_dump("MCP raw result", result.model_dump(mode="json", exclude_none=True), self.output)
        if result.isError:
            return {"ok": False, "error": "MCP 工具执行失败",
                    "content": result.model_dump(mode="json", exclude_none=True)["content"]}
        data = result.structuredContent
        if data is None:
            # 兼容只返回 TextContent 的 MCP 服务端；优先使用 SDK 结构化结果。
            text = "\n".join(block.text for block in result.content if block.type == "text")
            try:
                data = json.loads(text)
            except ValueError:
                data = {"text": text}
        return {"ok": True, "result": data}

