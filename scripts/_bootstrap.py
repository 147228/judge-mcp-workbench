import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# 重定向到文件时也保留中文，便于 Windows/macOS 留存运行证据。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

