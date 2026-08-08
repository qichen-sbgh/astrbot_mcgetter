"""Built-in status card themes for astrbot_mcgetter."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ..get_img import generate_server_info_image
from . import extra

RenderFn = Callable[..., Awaitable[str]]

# Canonical built-in theme IDs → (display label, renderer)
# `default` / `neon` share Design F.
BUILTIN_THEMES: Dict[str, Tuple[str, RenderFn]] = {
    "neon": ("霓虹玻璃（默认）", generate_server_info_image),
    "default": ("霓虹玻璃（默认别名）", generate_server_info_image),
    "classic": ("经典精修", extra.render_classic),
    "dashboard": ("现代仪表盘", extra.render_dashboard),
    "inventory": ("MC 背包风", extra.render_inventory),
    "soft": ("浅色柔和", extra.render_soft),
    "compact": ("紧凑信息流", extra.render_compact),
}

# Preferred listing order (skip alias default in list UI except as note)
LIST_ORDER = ["neon", "classic", "dashboard", "inventory", "soft", "compact"]

DEFAULT_THEME = "neon"


def normalize_theme_id(name: Optional[str]) -> str:
    raw = (name or "").strip().lower()
    if not raw:
        return DEFAULT_THEME
    if raw in BUILTIN_THEMES:
        return "neon" if raw == "default" else raw
    return raw


def is_builtin(name: str) -> bool:
    return name.strip().lower() in BUILTIN_THEMES


def list_builtin_entries() -> List[Tuple[str, str]]:
    """Return [(id, label), ...] for UI."""
    out: List[Tuple[str, str]] = []
    for tid in LIST_ORDER:
        label, _ = BUILTIN_THEMES[tid]
        out.append((tid, label))
    return out


async def render_builtin(
    theme_id: str,
    **kwargs: Any,
) -> Optional[str]:
    """
    Render with a built-in theme. Returns base64 PNG or None if unknown theme.
    """
    key = (theme_id or "").strip().lower()
    entry = BUILTIN_THEMES.get(key)
    if not entry:
        return None
    _, fn = entry
    return await fn(**kwargs)
