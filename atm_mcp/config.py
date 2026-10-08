import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MCP_URL = "http://127.0.0.1:8765/mcp"


def redact(text: str) -> str:
    """错误和 debug 日志不回显 API 密钥。"""
    for name in ("LLM_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        value = os.getenv(name)
        if value:
            text = text.replace(value, "[REDACTED]")
    return re.sub(r"sk-[A-Za-z0-9_-]{10,}", "[REDACTED]", text)


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    mcp_url: str = DEFAULT_MCP_URL
    timeout: float = 60

    @classmethod
    def load(cls) -> "Settings":
        # 路径相对项目，不受启动终端所在目录影响；环境变量优先于 .env。
        load_dotenv(ROOT / ".env")
        key = (os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
               or os.getenv("OPENAI_API_KEY") or "").strip()
        if not key:
            raise ValueError("缺少密钥：请在本地 .env 配置 DEEPSEEK_API_KEY 或 LLM_API_KEY")
        timeout = float(os.getenv("LLM_TIMEOUT", "60"))
        if timeout <= 0:
            raise ValueError("LLM_TIMEOUT 必须大于 0")
        return cls(
            api_key=key, base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
            model=os.getenv("LLM_MODEL", "deepseek-flash"),
            mcp_url=os.getenv("MCP_URL", DEFAULT_MCP_URL), timeout=timeout,
        )
