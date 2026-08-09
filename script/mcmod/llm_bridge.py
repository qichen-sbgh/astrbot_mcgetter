from __future__ import annotations

from typing import Any, List, Optional

from .models import McmodEntry


async def text_chat_summary(
    context: Any,
    *,
    umo: str,
    system_prompt: str,
    prompt: str,
) -> str:
    prov = None
    if hasattr(context, "get_using_provider"):
        try:
            prov = context.get_using_provider(umo=umo)
        except TypeError:
            prov = context.get_using_provider()
        except Exception:
            prov = None
    if prov is None and hasattr(context, "get_all_providers"):
        try:
            providers = context.get_all_providers() or []
            prov = providers[0] if providers else None
        except Exception:
            prov = None
    if not prov or not hasattr(prov, "text_chat"):
        return ""
    try:
        resp = await prov.text_chat(prompt=prompt, system_prompt=system_prompt)
        return (getattr(resp, "completion_text", None) or str(resp) or "").strip()
    except Exception:
        return ""


async def summarize_entry(
    context: Any,
    entry: McmodEntry,
    *,
    umo: str,
    style: str = "guide",
) -> str:
    if style == "guide":
        system = (
            "你是 Minecraft 模组百科导读助手。仅根据给定资料写 80-150 字中文导读，"
            "不编造版本/下载源；语气轻松适合群聊。"
        )
        prompt = f"请为以下 MC百科 条目写导读：\n{entry.summary_block()}"
    else:
        system = "你是 Minecraft 百科编辑。根据资料写不超过 60 字的一句话中文摘要，不编造。"
        prompt = f"一句话摘要：\n{entry.summary_block(max_raw=400)}"
    text = await text_chat_summary(context, umo=umo, system_prompt=system, prompt=prompt)
    return text


async def summarize_entries_batch(
    context: Any,
    entries: List[McmodEntry],
    *,
    umo: str,
) -> List[str]:
    if not entries:
        return []
    blocks = []
    for i, e in enumerate(entries, 1):
        blocks.append(f"[{i}] {e.summary_block(max_raw=300)}")
    system = (
        "你是 Minecraft 百科编辑。对每个编号条目写不超过 60 字中文摘要。"
        "严格按行输出：1. ... 2. ... 不编造。"
    )
    prompt = "请摘要：\n" + "\n\n".join(blocks)
    text = await text_chat_summary(context, umo=umo, system_prompt=system, prompt=prompt)
    if not text:
        return [e.short_desc or e.display_title() for e in entries]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: List[str] = []
    for i, e in enumerate(entries):
        found = ""
        for ln in lines:
            if ln.startswith(f"{i+1}.") or ln.startswith(f"{i+1}。") or ln.startswith(f"{i+1}、"):
                found = ln.split(".", 1)[-1].split("。", 1)[-1].split("、", 1)[-1].strip()
                break
        out.append(found or e.short_desc or e.display_title())
    return out


def format_link_preview(entry: McmodEntry, llm_summary: str = "") -> str:
    """导读（快速浏览）+ 详细信息（解析到的完整字段/介绍）。"""
    title = entry.display_title()
    guide = (llm_summary or "").strip()
    if not guide:
        guide = (entry.short_desc or entry.intro or "（暂无 LLM 导读，下方为百科解析详情）").strip()
        if len(guide) > 200:
            guide = guide[:200] + "…"

    lines = [
        f"【MC百科】{title}",
        "",
        "—— 导读 ——",
        guide,
        "",
        "—— 详细信息 ——",
        f"▸ 类型: {entry.kind_label()}" + (f"  |  ID: {entry.id}" if entry.id else ""),
    ]
    if entry.title_cn or entry.title_en:
        if entry.title_cn:
            lines.append(f"▸ 中文名: {entry.title_cn}")
        if entry.title_en:
            lines.append(f"▸ 英文名: {entry.title_en}")
    if entry.platform:
        lines.append(f"▸ 支持平台: {entry.platform}")
    if entry.loaders:
        lines.append(f"▸ 运作方式: {' / '.join(entry.loaders)}")
    if entry.environment:
        lines.append(f"▸ 运行环境: {entry.environment}")
    if entry.status:
        lines.append(f"▸ 状态: {entry.status}")
    if entry.categories:
        lines.append(f"▸ 分类: {' · '.join(entry.categories[:8])}")
    if entry.tags:
        lines.append(f"▸ 标签: {' · '.join(entry.tags[:12])}")
    if entry.authors:
        lines.append(f"▸ 作者/团队: {' · '.join(entry.authors[:10])}")
    if entry.version_detail:
        lines.append(f"▸ 版本支持: {entry.version_detail[:400]}")
    elif entry.mc_versions:
        lines.append(f"▸ MC版本: {', '.join(entry.mc_versions[:16])}")
    if entry.recorded_at:
        lines.append(f"▸ 收录时间: {entry.recorded_at}")
    if entry.edit_count:
        lines.append(f"▸ 编辑次数: {entry.edit_count}")
    if entry.last_edit:
        lines.append(f"▸ 最后编辑: {entry.last_edit}")

    intro = (entry.intro or entry.short_desc or "").strip()
    if intro:
        # 与导读去重：若几乎相同则仍展示完整介绍（导读是缩写）
        lines.append("")
        lines.append("▸ 百科介绍:")
        if len(intro) > 1200:
            intro = intro[:1200] + "…"
        for para in intro.split("\n"):
            para = para.strip()
            if para:
                lines.append(f"  {para}")

    if entry.related_links:
        lines.append("")
        lines.append("▸ 相关链接:")
        for label, href in entry.related_links[:8]:
            lines.append(f"  · {label}: {href}")

    lines.append("")
    lines.append(f"🔗 百科页面: {entry.url}")
    if not (llm_summary or "").strip():
        lines.append("（LLM 导读未生成，已展示解析详情）")
    return "\n".join(lines)


def format_push_message(items: List[tuple], *, title: str) -> str:
    """items: list of (label, entry, summary)"""
    lines = [title, ""]
    for i, (label, entry, summary) in enumerate(items, 1):
        lines.append(f"{i}️⃣ 【{label}】{entry.display_title()}")
        lines.append(f"   {summary or entry.short_desc or '…'}")
        lines.append(f"   🔗 {entry.url}")
        lines.append("")
    lines.append("数据来自 mcmod.cn · 可用 /mcmod push off 关闭")
    return "\n".join(lines)


def append_reference_links(answer: str, urls: List[str]) -> str:
    answer = (answer or "").rstrip()
    existing = answer.lower()
    missing = []
    for u in urls:
        if u and u.lower() not in existing:
            missing.append(u)
    if not missing and ("mcmod.cn" in existing or "参考" in answer):
        return answer
    if not urls:
        return answer
    lines = [answer, "", "📚 参考链接"]
    seen = set()
    idx = 1
    for u in urls:
        if not u or u in seen:
            continue
        seen.add(u)
        lines.append(f"{idx}. {u}")
        idx += 1
    return "\n".join(lines)
