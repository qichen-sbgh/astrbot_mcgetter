"""mcmod HTML 解析（纯函数，无网络）。"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag

from .models import McmodEntry
from .urls import classify_url, normalize_mcmod_url

BASE = "https://www.mcmod.cn"

_META_KEYS = (
    "支持平台",
    "运作方式",
    "运行环境",
    "收录时间",
    "编辑次数",
    "最后编辑",
    "最后推荐",
    "模组标签",
    "标签",
)


def _clean_text(s: str) -> str:
    s = re.sub(r"\[(?:h\d|mark|ban)[^\]]*\]", "", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _abs_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        return "https:" + href
    return urljoin(BASE + "/", href)


def _canon_loader(name: str) -> str:
    fl = (name or "").lower()
    return {
        "forge": "Forge",
        "fabric": "Fabric",
        "quilt": "Quilt",
        "neoforge": "NeoForge",
        "rift": "Rift",
        "liteloader": "LiteLoader",
    }.get(fl, name)


def _extract_meta_map(soup: BeautifulSoup) -> Dict[str, str]:
    """从 li/p/div 文本提取「键: 值」元信息。"""
    meta: Dict[str, str] = {}
    for el in soup.find_all(["li", "div", "p", "span", "dd", "td"]):
        t = _clean_text(el.get_text(" ", strip=True))
        if not t or len(t) > 400:
            continue
        for key in _META_KEYS:
            if key in t:
                # 支持「键: 值」或「键 值」
                m = re.search(rf"{re.escape(key)}\s*[:：]?\s*(.+)$", t)
                if m:
                    val = _clean_text(m.group(1))
                    # 去掉嵌套重复键
                    if val and key not in meta:
                        meta[key] = val
                break
    return meta


def _extract_related_links(soup: BeautifulSoup) -> List[Tuple[str, str]]:
    links: List[Tuple[str, str]] = []
    seen = set()
    # 优先「相关链接」区域附近
    anchors = soup.find_all("a", href=True)
    for a in anchors:
        href = a.get("href") or ""
        label = _clean_text(a.get_text()) or _clean_text(a.get("title") or "")
        if not label or len(label) > 40:
            continue
        abs_u = _abs_url(href)
        # 外链经 link.mcmod.cn 或常见平台
        if not any(
            x in abs_u
            for x in (
                "link.mcmod.cn",
                "curseforge.com",
                "modrinth.com",
                "github.com",
                "discord",
                "patreon",
                "youtube.com",
                "wiki",
            )
        ):
            # 仍允许带「官方」等文案的外链
            if label not in {"官方", "CurseForge", "Modrinth", "GitHub", "Discord", "WIKI", "Patreon", "YouTube", "Maven", "Crowdin", "MCBBS"}:
                continue
        if abs_u in seen:
            continue
        if "mcmod.cn/class" in abs_u or "mcmod.cn/modpack" in abs_u:
            continue
        seen.add(abs_u)
        links.append((label, abs_u))
        if len(links) >= 12:
            break
    return links


def _extract_authors(soup: BeautifulSoup, text_all: str) -> List[str]:
    authors: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        if "/author/" not in href:
            continue
        name = _clean_text(a.get_text())
        if name and name not in authors and len(name) < 40:
            authors.append(name)
        if len(authors) >= 15:
            break
    if not authors:
        m = re.search(r"Mod作者/开发团队[^\n]{0,40}", text_all)
        if m:
            # 后续名字难解析时略过
            pass
    return authors


def _extract_intro_paragraphs(soup: BeautifulSoup) -> Tuple[str, str]:
    """返回 (short_desc, intro)。intro 为拼接后的详细介绍。"""
    paras: List[str] = []
    for p in soup.find_all(["p", "div", "section", "article"]):
        # 跳过明显导航/侧栏
        cls = " ".join(p.get("class") or []).lower()
        if any(x in cls for x in ("nav", "menu", "footer", "header", "side", "rank", "ad")):
            continue
        t = _clean_text(p.get_text())
        if not t or len(t) < 25:
            continue
        if any(
            bad in t
            for bad in (
                "常用地址",
                "登录并",
                "MC百科|",
                "今日收录",
                "贡献榜",
                "添加模组",
                "创建教程",
            )
        ):
            continue
        # 元信息行不要当介绍
        if any(t.startswith(k) or f"{k}:" in t[:12] or f"{k}：" in t[:12] for k in _META_KEYS):
            continue
        if t not in paras:
            paras.append(t)
        if sum(len(x) for x in paras) > 2500:
            break

    if not paras:
        return "", ""
    short = paras[0][:400]
    intro = "\n".join(paras)
    if len(intro) > 2000:
        intro = intro[:2000] + "…"
    return short, intro


def _extract_version_detail(soup: BeautifulSoup, text_all: str) -> Tuple[str, List[str]]:
    detail_parts: List[str] = []
    for el in soup.find_all(["li", "div", "p"]):
        t = _clean_text(el.get_text(" ", strip=True))
        if "支持的MC版本" in t or (t.startswith("NeoForge") and re.search(r"1\.\d+", t)):
            if 5 < len(t) < 500 and t not in detail_parts:
                detail_parts.append(t)
        if "运作方式" in t and re.search(r"1\.\d+", t):
            if t not in detail_parts and len(t) < 400:
                detail_parts.append(t)

    versions = re.findall(r"\b(?:26\.\d+(?:\.\d+)?|1\.\d{1,2}(?:\.\d{1,2})?)\b", text_all)
    seen = set()
    mc_versions: List[str] = []
    for v in versions:
        if v not in seen:
            seen.add(v)
            mc_versions.append(v)
        if len(mc_versions) >= 24:
            break
    detail = " | ".join(detail_parts[:6])
    if not detail and mc_versions:
        detail = "支持版本: " + ", ".join(mc_versions[:16])
    return detail[:800], mc_versions


def parse_detail_html(html: str, page_url: str = "") -> McmodEntry:
    soup = BeautifulSoup(html or "", "lxml")
    url = normalize_mcmod_url(page_url) if page_url else ""
    kind, eid = classify_url(url) if url else ("unknown", "")

    if kind == "unknown":
        for a in soup.select('a[href*="/class/"], a[href*="/modpack/"]'):
            href = a.get("href") or ""
            k, i = classify_url(_abs_url(href))
            if k in {"mod", "modpack"}:
                kind, eid = k, i
                url = build_url(k, i)
                break

    entry = McmodEntry(
        kind=kind if kind != "unknown" else "mod",
        id=eid,
        url=url or build_url(kind, eid),
    )

    title_cn = ""
    title_en = ""
    h3 = soup.find("h3")
    if h3:
        title_cn = _clean_text(h3.get_text(" ", strip=True))
        nxt = h3.find_next_sibling(["h4", "h5", "p", "div", "span"])
        if nxt and len(_clean_text(nxt.get_text())) < 80:
            maybe_en = _clean_text(nxt.get_text())
            if re.search(r"[A-Za-z]", maybe_en):
                title_en = maybe_en
    if not title_cn:
        for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
            t = _clean_text(tag.get_text())
            if t and "MC百科" not in t and len(t) < 120:
                if re.search(r"[\u4e00-\u9fff]", t) and not title_cn:
                    title_cn = t
                elif re.search(r"[A-Za-z]", t) and not title_en:
                    title_en = t
                if title_cn and title_en:
                    break

    if not title_cn and soup.title:
        raw_title = _clean_text(soup.title.get_text())
        raw_title = re.sub(r"\s*[-|].*MC百科.*$", "", raw_title)
        m = re.match(r"^(.+?)\s*[\(（](.+?)[\)）]", raw_title)
        if m:
            title_cn, title_en = m.group(1).strip(), m.group(2).strip()
        else:
            title_cn = raw_title

    m2 = re.match(r"^(.+?)\s*[\(（](.+?)[\)）]\s*$", title_cn)
    if m2 and not title_en:
        title_cn, title_en = m2.group(1).strip(), m2.group(2).strip()

    entry.title_cn = title_cn
    entry.title_en = title_en

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if "class/cover" in src or "modpack/cover" in src:
            entry.cover = _abs_url(src)
            break

    text_all = soup.get_text("\n", strip=True)
    meta = _extract_meta_map(soup)

    # 加载器
    loaders: List[str] = []
    loader_src = meta.get("运作方式", "") + " " + text_all[:3000]
    for name in ("NeoForge", "Forge", "Fabric", "Quilt", "Rift", "LiteLoader"):
        if re.search(rf"\b{name}\b", loader_src, re.I) or name in loader_src:
            c = _canon_loader(name)
            if c not in loaders:
                loaders.append(c)
    entry.loaders = loaders

    entry.platform = meta.get("支持平台", "")
    entry.environment = meta.get("运行环境", "")
    entry.recorded_at = meta.get("收录时间", "")
    entry.edit_count = meta.get("编辑次数", "")
    entry.last_edit = meta.get("最后编辑", "") or meta.get("最后推荐", "")

    for st in ("活跃", "半弃坑", "停更"):
        if st in text_all[:2500]:
            entry.status = st
            break

    # 标签
    tags: List[str] = []
    tag_blob = meta.get("模组标签", "") or meta.get("标签", "")
    if tag_blob:
        for part in re.split(r"[,，·\|/\s]+", tag_blob):
            part = part.strip()
            if part and 1 < len(part) <= 20 and part not in tags:
                tags.append(part)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "key=" in href or "/s?" in href:
            t = _clean_text(a.get_text())
            if t and 1 < len(t) <= 20 and t not in tags:
                tags.append(t)
        if len(tags) >= 16:
            break
    entry.tags = tags[:16]

    # 分类（面包屑 category）
    cats: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        if "/class/category/" in href or "/modpack" in href and "category" in href:
            t = _clean_text(a.get_text())
            if t and t not in cats and len(t) < 30:
                cats.append(t)
    entry.categories = cats[:8]

    entry.authors = _extract_authors(soup, text_all)
    entry.version_detail, entry.mc_versions = _extract_version_detail(soup, text_all)
    entry.related_links = _extract_related_links(soup)

    short, intro = _extract_intro_paragraphs(soup)
    entry.short_desc = short
    entry.intro = intro
    if not entry.short_desc and entry.intro:
        entry.short_desc = entry.intro[:400]

    # raw_text
    soup2 = BeautifulSoup(html or "", "lxml")
    for tag in soup2(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    entry.raw_text = _clean_text(soup2.get_text("\n", strip=True))[:6000]

    if not entry.url and eid:
        entry.url = build_url(entry.kind, eid)
    return entry


def build_url(kind: str, eid: str) -> str:
    path = {"mod": "class", "modpack": "modpack", "item": "item", "post": "post"}.get(kind, "class")
    if not eid:
        return ""
    return f"https://www.mcmod.cn/{path}/{eid}.html"


def parse_list_html(html: str, default_kind: str = "mod") -> List[McmodEntry]:
    """解析 modlist / modpack 列表页。"""
    soup = BeautifulSoup(html or "", "lxml")
    entries: List[McmodEntry] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        abs_u = normalize_mcmod_url(_abs_url(href))
        kind, eid = classify_url(abs_u)
        if kind not in {"mod", "modpack"} or not eid:
            continue
        if abs_u in seen:
            continue
        title = _clean_text(a.get_text())
        if not title or len(title) > 100:
            parent = a.parent
            if parent:
                title = _clean_text(parent.get_text())
            if not title or len(title) > 120:
                continue
        short = _clean_text(a.get("title") or "")
        block = a.find_parent(["li", "div", "td", "article"])
        if block:
            for node in block.find_all(string=True):
                t = _clean_text(str(node))
                if 15 <= len(t) <= 200 and t != title and "暂无" not in t:
                    if not short or len(t) > len(short):
                        short = t
                    break
        seen.add(abs_u)
        entries.append(
            McmodEntry(
                kind=kind,
                id=eid,
                title_cn=title,
                url=abs_u,
                short_desc=short[:400],
                intro=short[:800],
            )
        )
    return entries


def parse_search_html(html: str) -> List[McmodEntry]:
    """解析 search.mcmod.cn 结果页。"""
    soup = BeautifulSoup(html or "", "lxml")
    entries: List[McmodEntry] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        if "mcmod.cn" not in href and not href.startswith("/class") and not href.startswith("/modpack"):
            if not re.search(r"/(class|modpack|item|post)/\d+", href):
                continue
        abs_u = normalize_mcmod_url(_abs_url(href) if "mcmod.cn" in href or href.startswith("/") else href)
        if "mcmod.cn" not in abs_u:
            if re.search(r"/(class|modpack|item|post)/\d+", href):
                abs_u = normalize_mcmod_url(_abs_url(href))
            else:
                continue
        kind, eid = classify_url(abs_u)
        if kind == "unknown" or not eid:
            continue
        if abs_u in seen:
            continue
        title = _clean_text(a.get_text())
        if not title or len(title) < 2:
            continue
        short = ""
        parent = a.find_parent(["li", "div", "article"])
        if parent:
            full = _clean_text(parent.get_text())
            short = full.replace(title, "", 1).strip()[:600]
        seen.add(abs_u)
        entries.append(
            McmodEntry(
                kind=kind,
                id=eid,
                title_cn=title,
                url=abs_u,
                short_desc=short[:400],
                intro=short,
                raw_text=short,
            )
        )
    return entries


def merge_feed_entries(
    mod_list: List[McmodEntry],
    pack_list: List[McmodEntry],
    *,
    limit: int = 10,
) -> List[McmodEntry]:
    """模组+整合包混排交错去重。"""
    out: List[McmodEntry] = []
    seen = set()
    i = j = 0
    while len(out) < limit and (i < len(mod_list) or j < len(pack_list)):
        if i < len(mod_list):
            e = mod_list[i]
            i += 1
            key = e.url or f"{e.kind}:{e.id}"
            if key not in seen:
                seen.add(key)
                out.append(e)
                if len(out) >= limit:
                    break
        if j < len(pack_list):
            e = pack_list[j]
            j += 1
            key = e.url or f"{e.kind}:{e.id}"
            if key not in seen:
                seen.add(key)
                out.append(e)
    return out
