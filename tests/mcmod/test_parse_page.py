from tests.mcmod.conftest import read_fixture
from script.mcmod.parse_page import parse_detail_html, parse_list_html, parse_search_html, merge_feed_entries


def test_parse_create_detail():
    html = read_fixture("class_2021_create.html")
    entry = parse_detail_html(html, "https://www.mcmod.cn/class/2021.html")
    assert entry.kind == "mod"
    assert entry.id == "2021"
    assert "机械动力" in entry.title_cn or "机械动力" in entry.display_title()
    assert entry.url.endswith("/class/2021.html")
    assert entry.loaders, "loaders should be nonempty"
    assert any(x in entry.loaders for x in ("Forge", "Fabric", "NeoForge"))
    assert entry.short_desc or entry.raw_text
    assert entry.raw_text
    # 完整字段
    assert "JAVA" in (entry.platform or "")
    assert entry.environment
    assert entry.intro and len(entry.intro) > 40
    assert entry.authors
    assert entry.related_links
    assert entry.recorded_at or entry.edit_count


def test_parse_modpack_detail():
    html = read_fixture("modpack_248.html")
    entry = parse_detail_html(html, "https://www.mcmod.cn/modpack/248.html")
    assert entry.kind == "modpack"
    assert "优化" in entry.display_title() or entry.title_cn
    assert entry.url.endswith("/modpack/248.html")


def test_parse_modlist():
    html = read_fixture("modlist_createtime.html")
    entries = parse_list_html(html)
    assert len(entries) >= 1
    for e in entries:
        assert e.title_cn
        assert e.url
        assert "class/" in e.url


def test_parse_search():
    html = read_fixture("search_create.html")
    entries = parse_search_html(html)
    assert len(entries) >= 1
    assert any("2021" in e.url for e in entries)
    assert all(e.title_cn and e.url for e in entries)


def test_merge_feed_mixed_mod_and_pack():
    mods = parse_list_html(read_fixture("modlist_createtime.html"))
    packs = parse_list_html(read_fixture("modpack_createtime.html"))
    merged = merge_feed_entries(mods, packs, limit=6)
    kinds = {e.kind for e in merged}
    assert "mod" in kinds
    assert "modpack" in kinds
    urls = [e.url for e in merged]
    assert len(urls) == len(set(urls))
