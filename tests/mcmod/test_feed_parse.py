from tests.mcmod.conftest import read_fixture
from script.mcmod.parse_page import parse_list_html, merge_feed_entries


def test_modpack_list_parses():
    packs = parse_list_html(read_fixture("modpack_createtime.html"))
    assert len(packs) >= 1
    assert all("modpack/" in p.url for p in packs)


def test_interleave_dedupe():
    mods = parse_list_html(read_fixture("modlist_createtime.html"))
    packs = parse_list_html(read_fixture("modpack_createtime.html"))
    # inject duplicate url into packs
    if mods:
        packs = [mods[0]] + packs
    merged = merge_feed_entries(mods, packs, limit=10)
    assert len({e.url for e in merged}) == len(merged)
