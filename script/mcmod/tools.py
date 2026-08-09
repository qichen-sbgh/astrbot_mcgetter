from __future__ import annotations

import re
from typing import Any, List

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import logger
from astrbot.api.star import Context
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult, ToolSet
from astrbot.core.astr_agent_context import AstrAgentContext

from .feed import fetch_detail, fetch_latest_mixed, fetch_random, fetch_updates_mixed
from .search import search_mcmod
from .urls import extract_mcmod_links, normalize_mcmod_url


def collect_urls_from_text(text: str) -> List[str]:
    found = extract_mcmod_links(text or "", limit=20)
    # also bare https links
    for m in re.finditer(r"https?://(?:www\.)?mcmod\.cn/(?:class|modpack|item|post)/\d+\.html", text or "", re.I):
        u = normalize_mcmod_url(m.group(0))
        if u not in found:
            found.append(u)
    return found


@dataclass
class McmodSearchTool(FunctionTool[AstrAgentContext]):
    name: str = "mcmod_search"
    description: str = (
        "Search MC百科 (mcmod.cn / search.mcmod.cn) for mods, modpacks, items or posts. "
        "Use before answering questions about Minecraft mods."
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Search keyword"},
                "filter": {
                    "type": "string",
                    "description": "all | mod | modpack | item | post. Default all.",
                },
                "limit": {"type": "number", "description": "Max results 1-10. Default 5."},
            },
            "required": ["keyword"],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        keyword = str(kwargs.get("keyword") or "").strip()
        if not keyword:
            return "keyword 不能为空"
        filt = str(kwargs.get("filter") or "all").strip().lower() or "all"
        try:
            limit = int(kwargs.get("limit") or 5)
        except Exception:
            limit = 5
        limit = max(1, min(limit, 10))
        try:
            entries = await search_mcmod(keyword, filter_type=filt, limit=limit)
        except Exception as e:
            return f"搜索失败: {e}"
        if not entries:
            return f"无结果: {keyword}"
        lines = [f"搜索「{keyword}」共 {len(entries)} 条:"]
        for i, e in enumerate(entries, 1):
            lines.append(f"{i}. [{e.kind}] {e.display_title()} | {e.url}")
            if e.short_desc:
                lines.append(f"   {e.short_desc[:160]}")
        return "\n".join(lines)


@dataclass
class McmodFetchPageTool(FunctionTool[AstrAgentContext]):
    name: str = "mcmod_fetch_page"
    description: str = (
        "Fetch and parse an MC百科 detail page by URL or id. "
        "URL like https://www.mcmod.cn/class/2021.html or numeric class id."
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full mcmod URL preferred"},
                "id": {"type": "string", "description": "Numeric id if no URL"},
                "kind": {
                    "type": "string",
                    "description": "mod|modpack|item|post when using id. Default mod.",
                },
            },
            "required": [],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        url = str(kwargs.get("url") or "").strip()
        eid = str(kwargs.get("id") or "").strip()
        kind = str(kwargs.get("kind") or "mod").strip().lower()
        if not url and eid:
            path = {"mod": "class", "class": "class", "modpack": "modpack", "item": "item", "post": "post"}.get(kind, "class")
            url = f"https://www.mcmod.cn/{path}/{eid}.html"
        if not url:
            return "请提供 url 或 id"
        url = normalize_mcmod_url(url)
        try:
            entry = await fetch_detail(url)
        except Exception as e:
            return f"抓取失败: {e}"
        return entry.summary_block(max_raw=2500)


@dataclass
class McmodFeedTool(FunctionTool[AstrAgentContext]):
    name: str = "mcmod_feed"
    description: str = (
        "Get MC百科 feed: random browse, latest additions, or recent updates. "
        "Mixes mods and modpacks for latest/updates."
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "random | latest | updates",
                },
                "limit": {"type": "number", "description": "For latest/updates, max items. Default 5."},
            },
            "required": ["kind"],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        kind = str(kwargs.get("kind") or "").strip().lower()
        try:
            limit = int(kwargs.get("limit") or 5)
        except Exception:
            limit = 5
        limit = max(1, min(limit, 10))
        try:
            if kind == "random":
                entry = await fetch_random()
                if not entry:
                    return "随便看看失败"
                return entry.summary_block()
            if kind == "latest":
                entries = await fetch_latest_mixed(limit=limit)
            elif kind in {"updates", "update", "recent"}:
                entries = await fetch_updates_mixed(limit=limit)
            else:
                return "kind 必须是 random / latest / updates"
        except Exception as e:
            return f"feed 失败: {e}"
        if not entries:
            return "无条目"
        lines = []
        for i, e in enumerate(entries, 1):
            lines.append(f"{i}. [{e.kind}] {e.display_title()} | {e.url}")
            if e.short_desc:
                lines.append(f"   {e.short_desc[:120]}")
        return "\n".join(lines)


def build_mcmod_toolset(context: Context) -> ToolSet:
    tmgr = context.get_llm_tool_manager()
    toolset = ToolSet()
    try:
        full_toolset = tmgr.get_full_tool_set()
        for tool in list(getattr(full_toolset, "tools", []) or []):
            if getattr(tool, "active", True):
                toolset.add_tool(tool)
    except Exception as e:
        logger.warning("mcmod merge full tools failed: %s", e)
    try:
        for builtin_tool in list(tmgr.iter_builtin_tools() or []):
            if getattr(builtin_tool, "active", True):
                toolset.add_tool(builtin_tool)
    except Exception as e:
        logger.warning("mcmod merge builtin tools failed: %s", e)

    toolset.add_tool(McmodSearchTool())
    toolset.add_tool(McmodFetchPageTool())
    toolset.add_tool(McmodFeedTool())
    return toolset
