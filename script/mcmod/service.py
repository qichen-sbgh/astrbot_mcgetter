from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, List, Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, StarTools
from astrbot.core.agent.hooks import BaseAgentRunHooks
from astrbot.core.agent.tool import ToolSet

from .feed import fetch_detail, fetch_latest_mixed, fetch_random, fetch_updates_mixed
from .llm_bridge import (
    append_reference_links,
    format_link_preview,
    format_push_message,
    summarize_entries_batch,
    summarize_entry,
)
from .models import McmodEntry
from .push_logic import can_push_more, record_push, should_trigger_cold_room
from .push_store import PushStore, default_store_path
from .search import search_mcmod
from .tools import build_mcmod_toolset, collect_urls_from_text
from .urls import extract_mcmod_links, normalize_mcmod_url

DATA_DIR = Path(StarTools.get_data_dir("astrbot_mcgetter"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SYSTEM = (
    "你是 Minecraft / MC百科 (mcmod.cn) 助手。必须先调用工具检索或读取页面再回答。"
    "严禁编造未在工具结果中出现的版本、作者、机制。"
    "回答用简洁中文，适合群聊；结尾列出参考链接（mcmod.cn）。"
)


class _TraceHooks(BaseAgentRunHooks):
    def __init__(self) -> None:
        self.tool_names: List[str] = []
        self.tool_results: List[str] = []

    async def on_tool_start(self, run_context, tool, tool_args) -> None:  # type: ignore[no-untyped-def]
        name = getattr(tool, "name", "")
        if name and name not in self.tool_names:
            self.tool_names.append(name)

    async def on_tool_end(self, run_context, tool, tool_args, result) -> None:  # type: ignore[no-untyped-def]
        if result is not None:
            self.tool_results.append(str(result)[:4000])


class McmodService:
    def __init__(self, get_config: Optional[Callable[[str, Any], Any]] = None) -> None:
        self._get_config = get_config or (lambda k, d: d)
        self.push_store = PushStore(default_store_path(DATA_DIR))
        self._user_cooldown: dict[str, float] = {}

    def _cfg(self, key: str, default: Any) -> Any:
        try:
            return self._get_config(key, default)
        except Exception:
            return default

    def _cooldown_ok(self, user_id: str) -> bool:
        sec = float(self._cfg("mcmod_user_cooldown_sec", 8) or 8)
        if sec <= 0:
            return True
        now = time.time()
        last = self._user_cooldown.get(user_id, 0)
        if now - last < sec:
            return False
        self._user_cooldown[user_id] = now
        return True

    async def handle_link_preview(self, event: AstrMessageEvent, context: Context) -> Optional[str]:
        if not bool(self._cfg("mcmod_enabled", True)):
            return None
        if not bool(self._cfg("mcmod_link_preview", True)):
            return None
        text = (event.message_str or "").strip()
        if text.startswith("/"):
            return None
        links = extract_mcmod_links(text, limit=2)
        if not links:
            return None
        blocks = []
        for url in links:
            try:
                entry = await fetch_detail(url, timeout=float(self._cfg("mcmod_request_timeout", 12) or 12))
            except Exception as e:
                logger.warning("mcmod link fetch failed %s: %s", url, e)
                blocks.append(f"【MC百科】无法解析链接：{url}")
                continue
            summary = ""
            try:
                summary = await summarize_entry(
                    context, entry, umo=event.unified_msg_origin, style="guide"
                )
            except Exception as e:
                logger.warning("mcmod summary failed: %s", e)
            blocks.append(format_link_preview(entry, summary))
        return "\n\n".join(blocks) if blocks else None

    async def ask_agent(self, event: AstrMessageEvent, context: Context) -> str:
        if not bool(self._cfg("mcmod_enabled", True)):
            return "MC百科功能已关闭。"
        user_id = event.get_sender_id() or "unknown"
        if not self._cooldown_ok(user_id):
            return "操作太快了，请稍后再试。"

        question = self._parse_question(event.message_str)
        if not question:
            return self.help_text()

        provider_id = await context.get_current_chat_provider_id(event.unified_msg_origin)
        tools = build_mcmod_toolset(context)
        hooks = _TraceHooks()
        prompt = (
            f"用户问题: {question}\n"
            "请先使用 mcmod_search / mcmod_fetch_page / mcmod_feed 等工具获取资料，再整理回答。"
            "回答末尾必须给出 mcmod.cn 参考链接。"
        )
        llm_resp = await context.tool_loop_agent(
            event=event,
            chat_provider_id=provider_id,
            prompt=prompt,
            tools=tools,
            system_prompt=DEFAULT_SYSTEM,
            max_steps=20,
            tool_call_timeout=60,
            agent_hooks=hooks,
        )
        answer = getattr(llm_resp, "completion_text", None) or "未能生成回答。"
        urls = collect_urls_from_text("\n".join(hooks.tool_results) + "\n" + answer)
        # also from question links
        urls = list(dict.fromkeys(extract_mcmod_links(question, limit=5) + urls))
        return append_reference_links(answer, urls)

    async def cmd_search(self, keyword: str, limit: int = 5) -> str:
        entries = await search_mcmod(keyword, limit=limit)
        if not entries:
            return f"未找到与「{keyword}」相关的百科结果。"
        lines = [f"🔍 MC百科搜索：{keyword}", ""]
        for i, e in enumerate(entries, 1):
            lines.append(f"{i}. {e.display_title()}")
            if e.short_desc:
                lines.append(f"   {e.short_desc[:120]}")
            lines.append(f"   🔗 {e.url}")
        return "\n".join(lines)

    async def cmd_info(self, token: str) -> str:
        token = (token or "").strip()
        if not token:
            return "用法：/mcmod info <url|classId|modpack/id>"
        url = token
        if re.fullmatch(r"\d+", token):
            url = f"https://www.mcmod.cn/class/{token}.html"
        elif token.startswith("modpack/"):
            url = f"https://www.mcmod.cn/{token}.html" if not token.endswith(".html") else f"https://www.mcmod.cn/{token}"
        url = normalize_mcmod_url(url)
        entry = await fetch_detail(url)
        # info 子命令：展示完整解析详情（无 LLM 时导读区回退短简介）
        return format_link_preview(entry, "")

    async def cmd_random(self, context: Context, umo: str) -> str:
        entry = await fetch_random()
        if not entry:
            return "随便看看失败，请稍后再试。"
        summary = await summarize_entry(context, entry, umo=umo, style="short")
        return format_link_preview(entry, summary)

    async def cmd_latest(self, n: int = 5) -> str:
        n = max(1, min(n, 10))
        entries = await fetch_latest_mixed(limit=n)
        return self._format_list("最新收录（模组+整合包）", entries)

    async def cmd_updates(self, n: int = 5) -> str:
        n = max(1, min(n, 10))
        entries = await fetch_updates_mixed(limit=n)
        return self._format_list("有新动态（模组+整合包）", entries)

    def _format_list(self, title: str, entries: List[McmodEntry]) -> str:
        if not entries:
            return f"{title}：暂无数据"
        lines = [f"📋 {title}", ""]
        for i, e in enumerate(entries, 1):
            kind_cn = "整合包" if e.kind == "modpack" else "模组"
            lines.append(f"{i}. [{kind_cn}] {e.display_title()}")
            if e.short_desc:
                lines.append(f"   {e.short_desc[:100]}")
            lines.append(f"   🔗 {e.url}")
        return "\n".join(lines)

    async def build_push_payload(self, context: Context, umo: str, n: int = 3) -> str:
        n = max(1, min(n, 6))
        items: List[tuple] = []
        try:
            latest = await fetch_latest_mixed(limit=4)
        except Exception:
            latest = []
        try:
            updates = await fetch_updates_mixed(limit=4)
        except Exception:
            updates = []
        try:
            rnd = await fetch_random()
        except Exception:
            rnd = None

        picked: List[tuple] = []
        if latest:
            picked.append(("最新", latest[0]))
        if updates:
            # prefer different url
            for u in updates:
                if not any(u.url == p[1].url for p in picked):
                    picked.append(("动态", u))
                    break
        if rnd and not any(rnd.url == p[1].url for p in picked):
            picked.append(("随便看看", rnd))
        # fill remaining from mixed
        for e in latest[1:] + updates:
            if len(picked) >= n:
                break
            if any(e.url == p[1].url for p in picked):
                continue
            label = "整合包" if e.kind == "modpack" else "最新"
            picked.append((label, e))

        picked = picked[:n]
        if not picked:
            return ""
        entries = [e for _, e in picked]
        # try enrich short list items with detail if no desc
        for i, (lab, e) in enumerate(picked):
            if not e.short_desc and e.url:
                try:
                    detailed = await fetch_detail(e.url)
                    picked[i] = (lab, detailed)
                    entries[i] = detailed
                except Exception:
                    pass
        summaries = await summarize_entries_batch(context, entries, umo=umo)
        for i, (lab, e) in enumerate(picked):
            items.append((lab, e, summaries[i] if i < len(summaries) else e.short_desc))
        now = time.strftime("%m-%d %H:%M")
        return format_push_message(items, title=f"📘 MC百科推送 | {now}")

    def help_text(self) -> str:
        return (
            "/mcmod <问题>  — 用工具检索 MC百科 后回答\n"
            "/mcmod search <关键词>\n"
            "/mcmod info <url|id>\n"
            "/mcmod random | latest [n] | updates [n]\n"
            "/mcmod push on|off|status|now\n"
            "/mcmod help"
        )

    @staticmethod
    def _parse_question(message_str: str) -> str:
        text = str(message_str or "").strip()
        parts = text.split()
        if parts and parts[0].lstrip("/").lower() == "mcmod":
            parts = parts[1:]
        return " ".join(parts).strip()


def parse_mcmod_subcommand(message_str: str) -> tuple[str, str]:
    """返回 (subcommand, rest)。主问答时 subcommand 为空字符串或 'ask'。"""
    text = str(message_str or "").strip()
    parts = text.split()
    if parts and parts[0].lstrip("/").lower() == "mcmod":
        parts = parts[1:]
    if not parts:
        return "help", ""
    head = parts[0].lower()
    known = {
        "search", "info", "random", "latest", "updates",
        "push", "help", "?", "config",
    }
    if head in known:
        return head, " ".join(parts[1:]).strip()
    return "ask", " ".join(parts).strip()
