"""使用真实云端模型进行验收，会消耗模型 token；每个场景单独保存证据。"""
import argparse
import asyncio
import json
import time
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import _bootstrap  # noqa: F401
from atm_mcp.agent import RepairAgent, create_llm
from atm_mcp.bridge import ToolBridge
from atm_mcp.config import ROOT, Settings, redact
from atm_mcp.transport import ProgressLog, connect

CASES = [
    ("闲聊", [("你好，今天心情不错。", 0)]),
    ("吞卡报修", [("请帮我报修 ATM-001，银行卡被吞了，屏幕提示无法退卡。", 1)]),
    ("范围外问题", [("我的手机黑屏了，请帮我修手机。", 0)]),
    ("缺号追问与多轮补充", [("我的银行卡被 ATM 吞了，请帮我报修。", 0), ("设备编号是 ATM-002。", 1)]),
]


async def run(args):
    settings = Settings.load()
    if args.url:
        settings = replace(settings, mcp_url=args.url)
    destination = Path(args.output)
    if not destination.is_absolute():
        destination = ROOT / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = {"kind": "real_cloud_llm_acceptance", "provider": settings.base_url,
              "model": settings.model, "at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
              "cases": [], "passed": False}
    async with connect(settings.mcp_url) as session, create_llm(settings) as llm:
        bridge = await ToolBridge.discover(session, args.debug)
        for label, turns in CASES:
            agent = RepairAgent(llm, bridge, settings)
            for prompt, expected_calls in turns:
                print(f"\n场景：{label}\n你> {prompt}")
                progress = ProgressLog()
                started = time.perf_counter()
                outcome = await agent.ask(prompt, progress.callback)
                if expected_calls:
                    await progress.wait_complete()
                passed = outcome.mcp_calls == expected_calls
                if expected_calls:
                    passed = passed and [e["progress"] for e in progress.events] == [1, 2, 3, 4]
                    passed = passed and any(
                        item["result"].get("ok") and
                        item["result"].get("result", {}).get("status") == "维修完成"
                        for item in outcome.tool_results
                    )
                item = {"case": label, "prompt": prompt, "expected_mcp_calls": expected_calls,
                        **asdict(outcome), "progress": progress.events,
                        "seconds": round(time.perf_counter() - started, 3), "passed": passed}
                report["cases"].append(item)
                destination.write_text(redact(json.dumps(report, ensure_ascii=False, indent=2)), encoding="utf-8")
                print("助手> " + outcome.reply)
                print(f"{'PASS' if passed else 'FAIL'} | MCP 调用={outcome.mcp_calls}，预期={expected_calls}")
    report["passed"] = all(item["passed"] for item in report["cases"])
    destination.write_text(redact(json.dumps(report, ensure_ascii=False, indent=2)), encoding="utf-8")
    print(f"\n证据：{destination}\n总 token：{sum(item['total_tokens'] for item in report['cases'])}")
    if not report["passed"]:
        raise RuntimeError("存在未通过的验收场景")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--url")
    parser.add_argument("--output", default="artifacts/live_acceptance.json")
    try:
        asyncio.run(run(parser.parse_args()))
    except Exception as error:
        parser.exit(1, redact(f"验收失败：{error}\n"))


if __name__ == "__main__":
    main()

