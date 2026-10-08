"""本测试不请求云端，不产生模型费用。HTTP 烟测另由直调脚本完成。"""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from mcp.types import CallToolResult, TextContent, Tool
from openai import AsyncOpenAI
from pydantic import ValidationError

from atm_mcp.agent import RepairAgent
from atm_mcp.bridge import ToolBridge
from atm_mcp.config import Settings
from atm_mcp.domain import RepairRequest, RepairService, STAGES


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["吞卡", "不出钞", "系统故障"])
async def test_business_nodes_and_unique_tickets(fault):
    service, events = RepairService(0), []

    async def progress(current, total, message):
        events.append((current, total, message))

    request = RepairRequest(atm_id="ATM-001", fault_type=fault, describe="故障发生，请报修")
    first = await service.repair(request, progress)
    second = await service.repair(request, progress)
    assert first.ticket_id != second.ticket_id
    assert first.status == "维修完成" and first.simulation
    assert [node.status for node in first.history] == list(STAGES)
    assert [event[0] for event in events[:4]] == [1, 2, 3, 4]
    assert all(event[1] == 4 for event in events)


@pytest.mark.parametrize("values", [
    {"atm_id": "   "}, {"atm_id": "ATM 001"}, {"describe": "  "},
    {"fault_type": "手机黑屏"}, {"extra": "unexpected"},
])
def test_bad_parameters_rejected(values):
    base = dict(atm_id="ATM-001", fault_type="吞卡", describe="卡被吞了")
    with pytest.raises(ValidationError):
        RepairRequest(**(base | values))


@pytest.mark.anyio
async def test_cancelled_ticket_never_marked_complete():
    service = RepairService(0)

    async def cancel(current, total, message):
        if current == 2:
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await service.repair(RepairRequest(atm_id="ATM-001", fault_type="吞卡", describe="卡被吞"), cancel)
    ticket = next(iter(service.tickets.values()))
    assert ticket.status == "处理中断"
    assert [node.status for node in ticket.history] == list(STAGES[:2])


class FakeSession:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments, progress_callback=None):
        self.calls.append((name, arguments))
        result = {"ticket_id": "ATM-test-001", "status": "维修完成", "simulation": True}
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(result))],
                              structuredContent=result)


def make_bridge():
    session = FakeSession()
    tool = Tool(name="atm_repair", description="报修", inputSchema=RepairRequest.model_json_schema())
    return ToolBridge(session, [tool])


def response(message):
    return {"id": "chatcmpl-test", "object": "chat.completion", "created": 1, "model": "test",
            "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"
                         if message.get("tool_calls") else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}


def tool_message(call_id):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": call_id,
        "type": "function", "function": {"name": "atm_repair", "arguments": json.dumps({
            "atm_id": "ATM-001", "fault_type": "吞卡", "describe": "卡被吞了"})}}]}


@pytest.mark.anyio
async def test_fc_round_trip_matching_ids_and_duplicate_guard():
    responses = [tool_message("call_1"), tool_message("call_2"),
                 {"role": "assistant", "content": "模拟工单 ATM-test-001 已完成。"}]
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response(responses[len(requests) - 1]))

    bridge = make_bridge()
    async with AsyncOpenAI(api_key="test-not-a-real-key", base_url="https://mock.invalid/v1",
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle))) as llm:
        agent = RepairAgent(llm, bridge, Settings(api_key="test", base_url="https://mock.invalid/v1"))
        result = await agent.ask("ATM-001 吞卡，请报修")
    assert result.mcp_calls == 1 and len(bridge.session.calls) == 1
    assert result.tool_results[1]["cached"]
    tool_messages = [message for message in requests[-1]["messages"] if message["role"] == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == ["call_1", "call_2"]
    assert all(json.loads(message["content"])["ok"] for message in tool_messages)
    assert requests[0]["tool_choice"] == "auto"
    assert "ATM-test-001" in result.reply


@pytest.mark.anyio
async def test_no_tool_calls_means_no_mcp_execution():
    def handle(request):
        return httpx.Response(200, json=response({"role": "assistant", "content": "你好！"}))

    bridge = make_bridge()
    async with AsyncOpenAI(api_key="test", base_url="https://mock.invalid/v1",
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle))) as llm:
        result = await RepairAgent(llm, bridge, Settings(api_key="test")).ask("你好")
    assert result.reply == "你好！" and result.mcp_calls == 0


@pytest.mark.anyio
async def test_unknown_tool_and_malformed_arguments_do_not_reach_mcp():
    bridge = make_bridge()
    for name, args in [("transfer_money", "{}"), ("atm_repair", "not JSON"),
                       ("atm_repair", '{"atm_id":"ATM-001"}'), ("atm_repair", "[]")]:
        assert not (await bridge.execute(name, args))["ok"]
    assert bridge.call_count == 0

