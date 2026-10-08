import argparse
import asyncio
from dataclasses import replace

import _bootstrap  # noqa: F401
from atm_mcp.agent import RepairAgent, create_llm
from atm_mcp.bridge import ToolBridge
from atm_mcp.config import Settings, redact
from atm_mcp.transport import ProgressLog, connect


async def run(args) -> None:
    settings = Settings.load()
    if args.url:
        settings = replace(settings, mcp_url=args.url)
    async with connect(settings.mcp_url) as session, create_llm(settings) as llm:
        bridge = await ToolBridge.discover(session, args.debug)
        agent = RepairAgent(llm, bridge, settings)
        print(f"ATM 模拟报修助手 | 模型：{settings.model} | 输入 /quit 退出、/reset 清空对话")
        while True:
            text = args.message if args.message is not None else await asyncio.to_thread(input, "你> ")
            text = text.strip()
            if text.lower() in ("/quit", "quit", "exit"):
                return
            if text == "/reset":
                agent = RepairAgent(llm, bridge, settings)
                print("已清空对话")
                continue
            if not text:
                if args.message is not None:
                    raise ValueError("消息不能为空")
                continue
            progress = ProgressLog()
            try:
                outcome = await agent.ask(text, progress.callback)
                print("助手> " + outcome.reply)
                if args.debug:
                    print(f"[debug] MCP 调用={outcome.mcp_calls} | LLM 请求={outcome.llm_requests} "
                          f"| tokens={outcome.total_tokens}")
            except Exception as error:
                print(redact(f"调用失败：{error}"))
                if args.message is not None:
                    raise
            if args.message is not None:
                return


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM 自动判断并调用远程 MCP 工具")
    parser.add_argument("--url", help="覆盖 .env 中的 MCP_URL")
    parser.add_argument("--message", help="单条消息模式；省略则进入多轮交互")
    parser.add_argument("--debug", action="store_true")
    try:
        asyncio.run(run(parser.parse_args()))
    except (KeyboardInterrupt, EOFError):
        print("已退出")
    except Exception as error:
        parser.exit(1, redact(f"客户端失败：{error}\n"))


if __name__ == "__main__":
    main()

