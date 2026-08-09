from script.mcmod.parse_page import parse_detail_html
from script.mcmod.llm_bridge import format_link_preview
from tests.mcmod.conftest import read_fixture


def test_preview_has_guide_and_detail_sections():
    entry = parse_detail_html(
        read_fixture("class_2021_create.html"),
        "https://www.mcmod.cn/class/2021.html",
    )
    text = format_link_preview(entry, "这是一段简短导读，方便快速了解机械动力。")
    assert "—— 导读 ——" in text
    assert "—— 详细信息 ——" in text
    assert "简短导读" in text
    assert "运作方式" in text or "Forge" in text
    assert "百科介绍" in text
    assert "机械动力" in text
    assert entry.url in text
    # 详细段应比导读更长
    assert len(text) > 200
