from tests.mcmod.conftest import read_fixture
from script.mcmod.parse_page import parse_search_html


def test_search_has_title_url_and_mixed_kinds():
    entries = parse_search_html(read_fixture("search_create.html"))
    assert len(entries) >= 2
    assert any(e.kind == "mod" for e in entries)
    # fixture includes a modpack link
    assert any(e.kind == "modpack" for e in entries)
    for e in entries:
        assert e.title_cn
        assert "mcmod.cn" in e.url
