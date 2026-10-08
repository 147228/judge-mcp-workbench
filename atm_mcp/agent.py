import json
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from openai import AsyncOpenAI

from .bridge import ToolBridge
from .config import Settings
from .domain import ProgressCallback
from .prompts import SYSTEM_PROMPT
from .transport import debug_dump


def create_llm(settings: Settings) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.api_key, base_url=settings.base_url,
        timeout=settings.timeout, max_retries=0,
        http_client=httpx.AsyncClient(trust_env=False, timeout=settings.timeout),
    )


@dataclass
class ChatOutcome:
    reply: str
    tool_results: list[dict] = field(default_factory=list)
    mcp_calls: int = 0
    llm_requests: int = 0
    total_tokens: int = 0


class RepairAgent:
    def __init__(self, llm, bridge: ToolBridge, settings: Settings, max_tool_rounds: int = 4):
        self.llm, self.bridge, self.settings = llm, bridge, settings
        self.max_tool_rounds = max_tool_rounds
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    async def ask(self, text: str, progress: ProgressCallback | None = None) -> ChatOutcome:
        self.messages.append({"role": "user", "content": text})
        outcome, cache = ChatOutcome(reply=""), {}
        calls_before = self.bridge.call_count
        for round_index in range(self.max_tool_rounds + 1):
            options = {}
            if urlparse(self.settings.base_url).hostname == "api.deepseek.com":
                # 课堂只看 Function Calling；关闭额外思考以减小耗时和 token 成本。
                options["extra_body"] = {"thinking": {"type": "disabled"}}
            completion = await self.llm.chat.completions.create(
                model=self.settings.model, messages=self.messages,
                tools=self.bridge.openai_tools,
                tool_choice="auto" if round_index < self.max_tool_rounds else "none",
                max_tokens=600, **options,
            )
            outcome.llm_requests += 1
            if completion.usage:
                outcome.total_tokens += completion.usage.total_tokens
            message = completion.choices[0].message
            # 保留原始 assistant.tool_calls，然后逐条回填对应 tool_call_id。
            payload = message.model_dump(mode="json", exclude_none=True)
            payload = {key: value for key, value in payload.items()
                       if key in ("role", "content", "tool_calls", "reasoning_content")}
            self.messages.append(payload)
            if not message.tool_calls:
                outcome.reply = message.content or "模型未返回文本，请检查模型是否支持工具调用。"
                outcome.mcp_calls = self.bridge.call_count - calls_before
                return outcome
            if round_index == self.max_tool_rounds:
                # 即使兼容端忽略 tool_choice=none，也不让模型无限建单。
                self.messages.pop()
                raise RuntimeError("模型超过工具调用轮数限制")
            if self.bridge.debug:
                debug_dump("tool_calls", payload["tool_calls"], self.bridge.output)
            for call in message.tool_calls:
                try:
                    canonical = json.dumps(json.loads(call.function.arguments), sort_keys=True, ensure_ascii=False)
                except ValueError:
                    canonical = call.function.arguments
                key = (call.function.name, canonical)
                cached = key in cache
                if not cached:
                    cache[key] = await self.bridge.execute(call.function.name, call.function.arguments, progress)
                result = cache[key]
                if cached and self.bridge.debug:
                    self.bridge.output("[debug] 重复请求使用本轮缓存，未重新建单")
                outcome.tool_results.append({"name": call.function.name, "result": result, "cached": cached})
                self.messages.append({"role": "tool", "tool_call_id": call.id,
                                      "content": json.dumps(result, ensure_ascii=False)})
        raise RuntimeError("未获得最终回复")

