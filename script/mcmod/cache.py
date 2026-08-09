from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple


class TtlCache:
    def __init__(self) -> None:
        self._store: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if not item:
            return None
        exp, val = item
        if exp < time.time():
            self._store.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any, ttl_sec: float) -> None:
        self._store[key] = (time.time() + max(0.0, ttl_sec), value)

    def clear(self) -> None:
        self._store.clear()


# 模块级共享缓存
GLOBAL_CACHE = TtlCache()
