"""可选在线冒烟：MCMOD_LIVE=1 pytest tests/mcmod/test_live_smoke.py

不依赖 pytest-asyncio，使用 asyncio.run。
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("MCMOD_LIVE", "").strip() not in {"1", "true", "yes"},
    reason="set MCMOD_LIVE=1 to run live smoke",
)


def test_live_create_detail():
    from script.mcmod.feed import fetch_detail

    entry = asyncio.run(fetch_detail("https://www.mcmod.cn/class/2021.html"))
    assert entry.title_cn or entry.title_en
    assert entry.url


def test_live_search():
    from script.mcmod.search import search_mcmod

    entries = asyncio.run(search_mcmod("机械动力", limit=3))
    assert len(entries) >= 1


def test_live_random():
    from script.mcmod.feed import fetch_random

    entry = asyncio.run(fetch_random())
    assert entry is not None
