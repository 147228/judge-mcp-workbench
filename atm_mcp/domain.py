"""工单业务只在服务端执行；客户端进度通知不承担状态维护职责。"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

FaultType = Literal["吞卡", "不出钞", "系统故障"]
STAGES = ("已受理", "运维人员派单", "现场检修", "维修完成")
ProgressCallback = Callable[[float, float | None, str | None], Awaitable[None]]


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


class RepairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    atm_id: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
        description="用户提供的 ATM 设备编号，例如 ATM-001。不可编造。",
    )
    fault_type: FaultType
    describe: str = Field(min_length=1, max_length=1000, description="用户描述的故障现象")


class StageEvent(BaseModel):
    status: str
    at: str


class RepairResult(BaseModel):
    ticket_id: str
    atm_id: str
    fault_type: FaultType
    describe: str
    status: str
    created_at: str
    history: list[StageEvent] = Field(default_factory=list)
    simulation: bool = True


class RepairService:
    def __init__(self, step_delay: float = 0.8):
        if step_delay < 0:
            raise ValueError("节点间隔不能为负数")
        self.step_delay = step_delay
        # 按要求使用内存：服务重启后工单会消失，不代表真实银行派单。
        self.tickets: dict[str, RepairResult] = {}

    async def repair(self, request: RepairRequest, report: ProgressCallback) -> RepairResult:
        ticket = RepairResult(
            ticket_id="ATM-" + uuid4().hex,
            **request.model_dump(), status=STAGES[0], created_at=now(),
        )
        self.tickets[ticket.ticket_id] = ticket
        try:
            for index, stage in enumerate(STAGES, start=1):
                if index > 1:
                    await asyncio.sleep(self.step_delay)
                # 此处推进状态机，然后通知客户端；progress 是通知，不是状态源。
                if len(ticket.history) != index - 1:
                    raise RuntimeError("工单节点顺序异常")
                ticket.status = stage
                ticket.history.append(StageEvent(status=stage, at=now()))
                await report(index, len(STAGES), f"{ticket.ticket_id} | {stage}（模拟）")
        except asyncio.CancelledError:
            ticket.status = "处理中断"
            raise
        except Exception:
            ticket.status = "处理失败"
            raise
        return ticket.model_copy(deep=True)

