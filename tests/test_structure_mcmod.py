"""结构门禁：确认主路径使用 tool_loop_agent / text_chat，配置默认开启链接导读。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_link_preview_default_true():
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    assert schema["mcmod_link_preview"]["default"] is True
    assert schema["mcmod_enabled"]["default"] is True


def test_main_uses_tool_loop_and_text_chat_paths():
    main_py = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "mcmod_cmd" in main_py
    assert "ask_agent" in main_py
    assert "handle_link_preview" in main_py
    assert "tool_loop_agent" in (ROOT / "script" / "mcmod" / "service.py").read_text(encoding="utf-8")
    llm = (ROOT / "script" / "mcmod" / "llm_bridge.py").read_text(encoding="utf-8")
    assert "text_chat" in llm


def test_version_180():
    meta = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
    assert "1.8.0" in meta
    assert "1.8.0" in (ROOT / "main.py").read_text(encoding="utf-8")


def test_parse_entry_point_on_fixture():
    from script.mcmod.parse_page import parse_detail_html

    html = (ROOT / "tests" / "mcmod" / "fixtures" / "class_2021_create.html").read_text(encoding="utf-8")
    entry = parse_detail_html(html, "https://www.mcmod.cn/class/2021.html")
    assert entry.kind == "mod"
    assert entry.loaders
