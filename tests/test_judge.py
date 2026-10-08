import json

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError

from atm_mcp.config import Settings
from atm_mcp.judge import Decision, JudgeRequest, judge


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("values", [
    {"state": " "}, {"question": " "}, {"options": ["one"]},
    {"options": ["one", "one"]}, {"options": ["one", " "]}, {"kind": "arbitrary"},
])
def test_judgment_requires_bounded_valid_input(values):
    base = dict(state="无法登录", question="给哪个团队？", kind="choice", options=["登录", "其它"])
    with pytest.raises(ValidationError):
        JudgeRequest(**(base | values))


@pytest.mark.parametrize("score", [0, 6, 2.5, True, "3"])
def test_score_has_real_integer_type_and_bounds(score):
    with pytest.raises(ValidationError):
        Decision(score=score, reason="判断依据", needs_review=False)


@pytest.mark.anyio
async def test_evidence_must_be_verbatim_and_unknown_choices_fail(monkeypatch):
    answer = {"choice": "登录", "boolean": None, "score": None, "reason": "登录问题",
              "evidence": ["无法登录", "模型编造的句子"], "needs_review": False}

    def handle(request):
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 1,
            "model": "test", "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(answer)}}]})

    def llm(settings):
        return AsyncOpenAI(api_key="test", base_url="https://mock.invalid/v1",
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))

    monkeypatch.setattr("atm_mcp.judge.create_llm", llm)
    monkeypatch.setattr(Settings, "load", lambda: Settings(api_key="test", base_url="https://mock.invalid/v1"))
    events = []
    async def progress(p, total, message):
        events.append(p)
    request = JudgeRequest(state="客户无法登录", question="给哪个团队？", kind="choice", options=["登录", "其它"])
    result = await judge(request, progress)
    assert result.decision.evidence == ["无法登录"]
    assert result.decision.needs_review
    assert result.probability is None and events == [1, 2, 3, 4]
    answer["choice"] = "任意未知团队"
    with pytest.raises(ValueError, match="候选范围外"):
        await judge(request, progress)

