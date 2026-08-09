from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class McmodEntry:
    kind: str = "unknown"  # mod | modpack | item | post | unknown
    id: str = ""
    title_cn: str = ""
    title_en: str = ""
    url: str = ""
    cover: Optional[str] = None
    short_desc: str = ""
    intro: str = ""  # 百科正文/较长介绍（解析自页面）
    loaders: List[str] = field(default_factory=list)
    mc_versions: List[str] = field(default_factory=list)
    version_detail: str = ""  # 支持的 MC 版本原文/整理
    tags: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    status: str = ""
    platform: str = ""  # 支持平台
    environment: str = ""  # 运行环境
    authors: List[str] = field(default_factory=list)
    recorded_at: str = ""  # 收录时间
    last_edit: str = ""
    edit_count: str = ""
    related_links: List[Tuple[str, str]] = field(default_factory=list)  # (label, url)
    raw_text: str = ""

    def display_title(self) -> str:
        if self.title_cn and self.title_en:
            return f"{self.title_cn} ({self.title_en})"
        return self.title_cn or self.title_en or self.url or "(untitled)"

    def kind_label(self) -> str:
        return {
            "mod": "模组",
            "modpack": "整合包",
            "item": "资料/物品",
            "post": "教程",
            "unknown": "条目",
        }.get(self.kind, self.kind or "条目")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["related_links"] = [{"label": a, "url": b} for a, b in self.related_links]
        return d

    def summary_block(self, max_raw: int = 1200) -> str:
        lines = [
            f"类型: {self.kind_label()} ({self.kind})",
            f"标题: {self.display_title()}",
            f"链接: {self.url}",
        ]
        if self.id:
            lines.append(f"ID: {self.id}")
        if self.platform:
            lines.append(f"支持平台: {self.platform}")
        if self.loaders:
            lines.append(f"运作方式/加载器: {', '.join(self.loaders)}")
        if self.environment:
            lines.append(f"运行环境: {self.environment}")
        if self.status:
            lines.append(f"状态: {self.status}")
        if self.tags:
            lines.append(f"标签: {', '.join(self.tags[:16])}")
        if self.categories:
            lines.append(f"分类: {', '.join(self.categories[:12])}")
        if self.authors:
            lines.append(f"作者: {', '.join(self.authors[:12])}")
        if self.version_detail:
            lines.append(f"版本说明: {self.version_detail[:500]}")
        elif self.mc_versions:
            lines.append(f"版本: {', '.join(self.mc_versions[:16])}")
        if self.recorded_at:
            lines.append(f"收录时间: {self.recorded_at}")
        if self.last_edit:
            lines.append(f"最后编辑: {self.last_edit}")
        if self.edit_count:
            lines.append(f"编辑次数: {self.edit_count}")
        if self.intro:
            lines.append(f"百科介绍: {self.intro[:max_raw]}")
        elif self.short_desc:
            lines.append(f"简介: {self.short_desc}")
        if self.related_links:
            links = "；".join(f"{n}:{u}" for n, u in self.related_links[:10])
            lines.append(f"相关链接: {links}")
        if self.raw_text and not self.intro:
            lines.append(f"正文摘录: {self.raw_text[:max_raw]}")
        return "\n".join(lines)
