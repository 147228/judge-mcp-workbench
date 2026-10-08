"""不加载 .env、不访问 LLM；独立验证 MCP 工具发现、进度通知和工单结果。"""
import argparse
import asyncio
import json

import _bootstrap  # noqa: F401
from atm_mcp.config import DEFAULT_MCP_URL, redact
from atm_mcp.domain import RepairRequest, STAGES
from atm_mcp.transport import ProgressLog, connect, debug_dump


async def demo(args) -> None:
    request = RepairRequest(atm_id=args.atm_id, fault_type=args.fault_type, describe=args.describe)
    progress = ProgressLog()
    async with connect(args.url) as session:
        tools = await session.list_tools()
        print("已发现工具：", ", ".join(tool.name for tool in tools.tools))
        if args.debug:
            debug_dump("list_tools", tools.model_dump(mode="json", exclude_none=True))
        result = await session.call_tool("atm_repair", request.model_dump(), progress_callback=progress.callback)
        if args.debug:
            debug_dump("MCP raw result", result.model_dump(mode="json", exclude_none=True))
        if result.isError:
            raise RuntimeError("工具执行失败：" + str(result.content))
        await progress.wait_complete()
        if [event["progress"] for event in progress.events] != [1, 2, 3, 4]:
            raise RuntimeError("四节点 progress 验收未通过")
        data = result.structuredContent
        if not data or data.get("status") != STAGES[-1] or not data.get("ticket_id"):
            raise RuntimeError("最终工单结果验收未通过")
        print("最终结果：", json.dumps(data, ensure_ascii=False, indent=2))
        print(f"PASS | ticket_id={data['ticket_id']} | status={data['status']} | 四节点进度齐全")


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP 直调演示（不需要模型和密钥）")
    parser.add_argument("--url", default=DEFAULT_MCP_URL)
    parser.add_argument("--atm-id", default="ATM-001")
    parser.add_argument("--fault-type", choices=["吞卡", "不出钞", "系统故障"], default="吞卡")
    parser.add_argument("--describe", default="银行卡被吞入，屏幕提示暂时无法退卡")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(demo(args))
    except KeyboardInterrupt:
        print("演示已中断")
    except Exception as error:
        parser.exit(1, redact(f"直调失败：{error}\n请确认服务端正在运行、URL 正确。\n"))


if __name__ == "__main__":
    main()

