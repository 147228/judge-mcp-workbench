import argparse
from typing import Annotated

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from .domain import FaultType, RepairRequest, RepairResult, RepairService


def create_server(host: str = "127.0.0.1", port: int = 8765, step_delay: float = 0.8,
                  debug: bool = False) -> FastMCP:
    service = RepairService(step_delay)
    server = FastMCP(
        "ATM Repair Demo", host=host, port=port, streamable_http_path="/mcp",
        # 必须使用 SSE 响应流，才能在最终结果之前发送 progress 通知。
        json_response=False, stateless_http=False, log_level="DEBUG" if debug else "WARNING",
    )

    @server.tool()
    async def atm_repair(
        atm_id: Annotated[str, Field(min_length=1, max_length=64,
                                    pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
                                    description="用户提供的设备编号，如 ATM-001；不可编造")],
        fault_type: FaultType,
        describe: Annotated[str, Field(min_length=1, max_length=1000,
                                      description="用户描述的故障现象")],
        ctx: Context,
    ) -> RepairResult:
        """创建 ATM 模拟报修工单并推进四个节点。仅处理吞卡、不出钞、系统故障。

        仅在用户明确提出报修且设备编号、故障类型和现象齐全时调用。
        闲聊、咨询、查询已有工单或范围外问题不能调用本工具。
        返回模拟工单，不能据此声称真实 ATM 已完成维修。
        """
        request = RepairRequest(atm_id=atm_id, fault_type=fault_type, describe=describe)
        # Context 由 SDK 注入，不会作为工具参数暴露给模型。
        return await service.repair(request, ctx.report_progress)

    @server.tool()
    async def quick_judge(
        state: Annotated[str, Field(min_length=1, max_length=12000, description="待分析的原文或上下文")],
        question: Annotated[str, Field(min_length=1, max_length=1500, description="明确的判断问题和标准")],
        kind: Annotated[str, Field(pattern="^(choice|boolean|score)$", description="分类、是非或 1~5 评分")],
        ctx: Context,
        options: list[str] | None = None,
    ) -> dict:
        """对材料执行只读、结构化的窄判断：分类分流、条件检查或等级评分。

        实际调用配置的云端模型，会消耗 token；此工具不创建工单、不执行其它业务动作。
        """
        from .judge import JudgeRequest, judge
        request = JudgeRequest(state=state, question=question, kind=kind, options=options or [])
        return (await judge(request, ctx.report_progress)).model_dump(mode="json")

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="ATM MCP Streamable HTTP 服务端")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--step-delay", type=float, default=0.8)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.step_delay < 0:
        parser.error("端口须在 1~65535，节点间隔须非负")
    print(f"MCP 服务：http://{args.host}:{args.port}/mcp | 工单为教学模拟", flush=True)
    try:
        create_server(args.host, args.port, args.step_delay, args.debug).run(transport="streamable-http")
    except KeyboardInterrupt:
        print("MCP 服务已停止", flush=True)


if __name__ == "__main__":
    main()
