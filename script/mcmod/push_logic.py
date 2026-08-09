"""推送纯逻辑：概率、日计数、是否触发（无网络/LLM）。"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Optional


def cold_room_probability(idle_minutes: float, today_push_count: int) -> float:
    """p = idle*3 - 10*today_count；无 80% cap。可为负。"""
    return float(idle_minutes) * 3.0 - 10.0 * int(today_push_count)


def should_trigger_cold_room(
    idle_minutes: float,
    today_push_count: int,
    *,
    idle_skip_minutes: float = 10.0,
    daily_cap: int = 4,
    rng: Optional[random.Random] = None,
) -> bool:
    if idle_minutes < idle_skip_minutes:
        return False
    if daily_cap > 0 and today_push_count >= daily_cap:
        return False
    p = cold_room_probability(idle_minutes, today_push_count)
    if p <= 0:
        return False
    r = (rng or random).random() * 100.0
    return r < p


@dataclass
class PushGroupState:
    enabled: bool = False
    umo: str = ""
    group_id: str = ""
    last_human_msg_at: float = 0.0
    today_push_count: int = 0
    today_date: str = ""
    last_push_at: float = 0.0
    last_push_kind: str = ""
    enabled_at: float = 0.0

    def ensure_today(self, now: Optional[datetime] = None) -> None:
        d = (now or datetime.now()).date().isoformat()
        if self.today_date != d:
            self.today_date = d
            self.today_push_count = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "umo": self.umo,
            "group_id": self.group_id,
            "last_human_msg_at": self.last_human_msg_at,
            "today_push_count": self.today_push_count,
            "today_date": self.today_date,
            "last_push_at": self.last_push_at,
            "last_push_kind": self.last_push_kind,
            "enabled_at": self.enabled_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PushGroupState":
        return cls(
            enabled=bool(data.get("enabled", False)),
            umo=str(data.get("umo") or ""),
            group_id=str(data.get("group_id") or ""),
            last_human_msg_at=float(data.get("last_human_msg_at") or 0),
            today_push_count=int(data.get("today_push_count") or 0),
            today_date=str(data.get("today_date") or ""),
            last_push_at=float(data.get("last_push_at") or 0),
            last_push_kind=str(data.get("last_push_kind") or ""),
            enabled_at=float(data.get("enabled_at") or 0),
        )


def record_push(state: PushGroupState, kind: str, now_ts: float) -> PushGroupState:
    state.ensure_today(datetime.fromtimestamp(now_ts))
    state.today_push_count += 1
    state.last_push_at = now_ts
    state.last_push_kind = kind
    return state


def can_push_more(state: PushGroupState, daily_cap: int = 4, now: Optional[datetime] = None) -> bool:
    state.ensure_today(now)
    if daily_cap <= 0:
        return True
    return state.today_push_count < daily_cap
