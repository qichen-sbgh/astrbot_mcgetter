from __future__ import annotations

from typing import List, Optional

from .client import fetch_text
from .models import McmodEntry
from .parse_page import merge_feed_entries, parse_detail_html, parse_list_html
from .urls import classify_url, normalize_mcmod_url

LATEST_MOD = "https://www.mcmod.cn/modlist.html?sort=createtime"
LATEST_PACK = "https://www.mcmod.cn/modpack.html?sort=createtime"
UPDATES_MOD = "https://www.mcmod.cn/modlist.html?sort=lastedittime"
UPDATES_PACK = "https://www.mcmod.cn/modpack.html?sort=lastedittime"
RANDOM_URL = "https://www.mcmod.cn/rand/"


async def fetch_latest_mixed(limit: int = 10, timeout: float = 12.0) -> List[McmodEntry]:
    _, mod_html = await fetch_text(LATEST_MOD, timeout=timeout, cache_ttl=600)
    _, pack_html = await fetch_text(LATEST_PACK, timeout=timeout, cache_ttl=600)
    mods = parse_list_html(mod_html, "mod")
    packs = parse_list_html(pack_html, "modpack")
    return merge_feed_entries(mods, packs, limit=limit)


async def fetch_updates_mixed(limit: int = 10, timeout: float = 12.0) -> List[McmodEntry]:
    _, mod_html = await fetch_text(UPDATES_MOD, timeout=timeout, cache_ttl=600)
    _, pack_html = await fetch_text(UPDATES_PACK, timeout=timeout, cache_ttl=600)
    mods = parse_list_html(mod_html, "mod")
    packs = parse_list_html(pack_html, "modpack")
    return merge_feed_entries(mods, packs, limit=limit)


async def fetch_random(timeout: float = 12.0, retries: int = 3) -> Optional[McmodEntry]:
    for _ in range(max(1, retries)):
        final, html = await fetch_text(RANDOM_URL, timeout=timeout, cache_ttl=0, allow_redirects=True)
        final = normalize_mcmod_url(final)
        kind, eid = classify_url(final)
        if kind in {"mod", "modpack", "item", "post"} and eid:
            entry = parse_detail_html(html, final)
            return entry
    return None


async def fetch_detail(url: str, timeout: float = 12.0) -> McmodEntry:
    url = normalize_mcmod_url(url)
    final, html = await fetch_text(url, timeout=timeout, cache_ttl=6 * 3600)
    return parse_detail_html(html, final or url)
