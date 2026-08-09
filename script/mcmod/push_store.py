from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict

from .push_logic import PushGroupState


def default_store_path(data_dir: Path) -> Path:
    return Path(data_dir) / "mcmod_push.json"


class PushStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._states: Dict[str, PushGroupState] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._states = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._states = {}
            return
        states = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(v, dict):
                    states[str(k)] = PushGroupState.from_dict(v)
        self._states = states

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v.to_dict() for k, v in self._states.items()}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def has(self, key: str) -> bool:
        return key in self._states

    def get(self, key: str) -> PushGroupState:
        st = self._states.get(key)
        if st is None:
            st = PushGroupState()
            self._states[key] = st
        return st

    def all_enabled(self) -> Dict[str, PushGroupState]:
        return {k: v for k, v in self._states.items() if v.enabled and v.umo}

    def enable(self, key: str, umo: str, group_id: str = "") -> PushGroupState:
        st = self.get(key)
        st.enabled = True
        st.umo = umo
        st.group_id = group_id or st.group_id
        now = time.time()
        st.enabled_at = now
        if not st.last_human_msg_at:
            st.last_human_msg_at = now
        self.save()
        return st

    def disable(self, key: str) -> PushGroupState:
        st = self.get(key)
        st.enabled = False
        self.save()
        return st

    def touch_human(self, key: str, ts: float | None = None) -> None:
        st = self.get(key)
        st.last_human_msg_at = float(ts if ts is not None else time.time())
        # 不每次 save 磁盘可优化；此处简单 save
        self.save()

    def update(self, key: str, state: PushGroupState) -> None:
        self._states[key] = state
        self.save()
