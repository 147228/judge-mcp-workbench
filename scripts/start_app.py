"""一条命令启动两个独立进程；只管理本脚本创建的进程。"""
import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="启动 MCP 服务端和 JUDGE 网页工作台")
    parser.add_argument("--port", type=int, default=8800, help="网页端口")
    args = parser.parse_args()
    if args.port == 8765 or not 1 <= args.port <= 65535:
        parser.error("网页端口须在 1~65535，且不能与 MCP 的 8765 相同")
    # 预先验证端口，避免误连接别人的服务或终止已有进程。
    for port in (8765, args.port):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                parser.exit(1, f"端口 {port} 已占用。可分终端运行服务；请先确认占用者。\n")
    children = []
    try:
        children.append(subprocess.Popen([sys.executable, "scripts/mcp_server.py"], cwd=ROOT))
        children.append(subprocess.Popen([sys.executable, "scripts/web_server.py", "--port", str(args.port)], cwd=ROOT))
        print(f"JUDGE 工作台：http://127.0.0.1:{args.port}；Ctrl+C 停止本次启动的服务。", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
