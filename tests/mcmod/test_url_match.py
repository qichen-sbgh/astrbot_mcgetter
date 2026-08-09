from script.mcmod.urls import (
    classify_url,
    extract_mcmod_links,
    normalize_mcmod_url,
    is_mcmod_entity_url,
)


def test_extract_class_modpack_item_post():
    text = (
        "看看这个 https://www.mcmod.cn/class/2021.html "
        "和 http://mcmod.cn/modpack/248.html "
        "还有 www.mcmod.cn/item/123.html 以及 mcmod.cn/post/3312.html"
    )
    links = extract_mcmod_links(text, limit=10)
    assert len(links) >= 4
    kinds = {classify_url(u)[0] for u in links}
    assert "mod" in kinds
    assert "modpack" in kinds
    assert "item" in kinds
    assert "post" in kinds


def test_normalize_and_limit():
    text = "a https://www.mcmod.cn/class/1.html b https://www.mcmod.cn/class/1.html c https://www.mcmod.cn/class/2.html"
    links = extract_mcmod_links(text, limit=1)
    assert len(links) == 1
    assert links[0] == "https://www.mcmod.cn/class/1.html"


def test_classify():
    assert classify_url("https://www.mcmod.cn/class/2021.html") == ("mod", "2021")
    assert is_mcmod_entity_url("https://www.mcmod.cn/modpack/248.html")
    assert normalize_mcmod_url("www.mcmod.cn/class/9.html").startswith("https://")
