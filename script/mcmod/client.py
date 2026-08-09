from __future__ import annotations

import asyncio
from typing import Optional, Tuple

try:
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None  # type: ignore

from .cache import GLOBAL_CACHE

DEFAULT_UA = "AstrBot-MCGetter/1.8.0 (+plugin; polite)"
DEFAULT_TIMEOUT = 12.0
DEFAULT_CONCURRENCY = 3

_semaphore: Optional[asyncio.Semaphore] = None


def _sem(limit: int = DEFAULT_CONCURRENCY) -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(limit)
    return _semaphore


async def fetch_text(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    cache_ttl: float = 0,
    cache_key: Optional[str] = None,
    allow_redirects: bool = True,
    user_agent: str = DEFAULT_UA,
) -> Tuple[str, str]:
    """GET url，返回 (final_url, text)。cache_ttl>0 时缓存 body+url。"""
    key = cache_key or f"GET:{url}"
    if cache_ttl > 0:
        hit = GLOBAL_CACHE.get(key)
        if hit is not None:
            return hit[0], hit[1]

    if aiohttp is None:
        raise RuntimeError("aiohttp 未安装")

    async with _sem():
        timeout_cfg = aiohttp.ClientTimeout(total=timeout)
        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        }
        async with aiohttp.ClientSession(timeout=timeout_cfg, headers=headers) as session:
            async with session.get(url, allow_redirects=allow_redirects) as resp:
                text = await resp.text(errors="replace")
                final = str(resp.url)
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status} for {url}")
                if cache_ttl > 0:
                    GLOBAL_CACHE.set(key, (final, text), cache_ttl)
                return final, text
