from __future__ import annotations

from typing import List
from urllib.parse import quote

from .client import fetch_text
from .models import McmodEntry
from .parse_page import parse_search_html

SEARCH_BASE = "https://search.mcmod.cn/s"


async def search_mcmod(
    keyword: str,
    *,
    filter_type: str = "all",
    limit: int = 8,
    timeout: float = 12.0,
) -> List[McmodEntry]:
    """filter_type: all | mod | modpack | item | post"""
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    fmap = {"all": "0", "mod": "1", "modpack": "2", "item": "3", "post": "4"}
    filt = fmap.get((filter_type or "all").lower(), "0")
    url = f"{SEARCH_BASE}?key={quote(keyword)}&filter={filt}"
    _, html = await fetch_text(url, timeout=timeout, cache_ttl=900)
    entries = parse_search_html(html)
    return entries[: max(1, limit)]
