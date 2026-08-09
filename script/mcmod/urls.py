"""mcmod URL 识别与规范化。"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

# 匹配聊天中的 mcmod 实体链接
MCMOD_LINK_RE = re.compile(
    r"(?i)(?:https?://)?(?:www\.)?mcmod\.cn/"
    r"(class|modpack|item|post)/(\d+)(?:\.html)?(?:[^\s<>\"']*)?"
)

ENTITY_PATH_RE = re.compile(
    r"(?i)/(class|modpack|item|post)/(\d+)(?:\.html)?"
)

KIND_MAP = {
    "class": "mod",
    "modpack": "modpack",
    "item": "item",
    "post": "post",
}


def normalize_mcmod_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if not re.match(r"(?i)^https?://", url):
        if "mcmod.cn" in url:
            url = "https://" + url.lstrip("/")
        else:
            return url
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    # 保留 search.mcmod.cn 等子域
    if host.endswith("mcmod.cn") and not host.startswith("search.") and host != "mcmod.cn":
        # i.mcmod.cn 等静态域不改
        pass
    path = parsed.path or ""
    m = ENTITY_PATH_RE.search(path)
    if m and host in {"mcmod.cn", "www.mcmod.cn"}:
        kind_path, eid = m.group(1).lower(), m.group(2)
        path = f"/{kind_path}/{eid}.html"
        return urlunparse(("https", "www.mcmod.cn", path, "", "", ""))
    # 统一 www
    if host == "mcmod.cn":
        host = "www.mcmod.cn"
    scheme = "https"
    return urlunparse((scheme, host, path, "", parsed.query, ""))


def classify_url(url: str) -> Tuple[str, str]:
    """返回 (kind, id)。未知则为 (unknown, '')."""
    url = normalize_mcmod_url(url)
    m = ENTITY_PATH_RE.search(urlparse(url).path or "")
    if not m:
        return "unknown", ""
    return KIND_MAP.get(m.group(1).lower(), "unknown"), m.group(2)


def extract_mcmod_links(text: str, limit: int = 2) -> List[str]:
    """从聊天文本提取规范化实体链接（去重，最多 limit）。"""
    if not text:
        return []
    seen = set()
    out: List[str] = []
    for m in MCMOD_LINK_RE.finditer(text):
        kind_path, eid = m.group(1).lower(), m.group(2)
        url = f"https://www.mcmod.cn/{kind_path}/{eid}.html"
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= limit:
            break
    return out


def is_mcmod_entity_url(url: str) -> bool:
    kind, eid = classify_url(url)
    return kind != "unknown" and bool(eid)


def build_entity_url(kind: str, eid: str) -> str:
    path_kind = {
        "mod": "class",
        "class": "class",
        "modpack": "modpack",
        "item": "item",
        "post": "post",
    }.get((kind or "").lower(), "")
    if not path_kind or not eid:
        return ""
    return f"https://www.mcmod.cn/{path_kind}/{eid}.html"
