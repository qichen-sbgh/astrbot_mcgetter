"""
Built-in themes A–E adapted from design prototypes for production cards.
Supports online/offline, MOTD, server name color, and player chip colors.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter

from ..get_img import (
    _draw_progress,
    _latency_tone,
    _paint_chips,
    _paint_tag_chips,
    _parse_rgb,
    _paste_rounded,
    _rounded_mask,
    _text_w,
    _to_base64,
    _truncate,
    _wrap_chips,
    fetch_icon,
    load_font,
    normalize_tags,
)


async def _prep(
    icon_base64: Optional[str],
    icon_size: int,
    players_list: list,
    chip_f,
    max_chip_w: int,
    is_off: bool,
    max_players: int = 22,
):
    icon = await fetch_icon(icon_base64)
    icon = icon.resize((icon_size, icon_size), Image.Resampling.NEAREST)
    tmp = Image.new("RGB", (10, 10))
    dtmp = ImageDraw.Draw(tmp)
    show = [] if is_off else list(players_list or [])[:max_players]
    lines, chip_h = _wrap_chips(dtmp, show, chip_f, max_chip_w, max_lines=3)
    return icon, lines, chip_h


def _title_color(server_name_color: Optional[str], fallback: Tuple[int, int, int]) -> Tuple[int, int, int]:
    return _parse_rgb(server_name_color) or fallback


def _motd_line(
    draw: ImageDraw.ImageDraw,
    motd: Optional[str],
    is_off: bool,
    x: int,
    y: int,
    font,
    max_w: int,
    fill: Tuple[int, int, int],
) -> int:
    """Draw MOTD if present; return vertical advance."""
    text = (motd or "").strip()
    if is_off or not text:
        return 0
    draw.text((x, y), _truncate(draw, text, font, max_w), font=font, fill=fill)
    return 20


# ---------------------------------------------------------------------------
# Classic (A)
# ---------------------------------------------------------------------------

async def render_classic(
    players_list: list,
    latency: int,
    server_name: str,
    plays_max: int,
    plays_online: int,
    server_version: str,
    icon_base64: Optional[str] = None,
    server_id: Optional[str] = None,
    host: Optional[str] = None,
    online_state: str = "online",
    last_success_text: Optional[str] = None,
    server_name_color: Optional[str] = None,
    player_colors: Optional[Dict[str, str]] = None,
    motd: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> str:
    W, pad = 640, 20
    is_off = online_state != "online"
    lat_c, lat_label = _latency_tone(latency if not is_off else -1)
    tag_list = normalize_tags(tags)
    title_f = await load_font(28)
    body_f = await load_font(18)
    small_f = await load_font(15)
    chip_f = await load_font(14)
    tag_f = await load_font(13)
    icon, lines, chip_h = await _prep(icon_base64, 72, players_list, chip_f, W - pad * 2 - 24, is_off)
    motd_h = 0 if is_off or not (motd or "").strip() else 20
    tag_h = 26 if tag_list else 0
    content_h = 120 if is_off else 168 + motd_h + (len(lines) * (chip_h + 8) if lines else 28)
    H = max(200, content_h + pad * 2 + tag_h)

    img = Image.new("RGB", (W, H), (28, 30, 34))
    draw = ImageDraw.Draw(img)
    accent = (70, 200, 110) if not is_off else (200, 80, 80)
    draw.rounded_rectangle((8, 8, W - 9, H - 9), 14, outline=accent, width=2)
    draw.rounded_rectangle((12, 16, 18, H - 16), 3, fill=accent)
    _paste_rounded(img, icon, (pad + 12, pad), 14)

    tx = pad + 12 + 72 + 16
    tc = _title_color(server_name_color, (230, 255, 235) if not is_off else (255, 210, 210))
    draw.text((tx, pad), _truncate(draw, server_name or "未知服务器", title_f, W - tx - pad - 100), font=title_f, fill=tc)

    status = "离线" if is_off else "在线"
    sc = (200, 70, 70) if is_off else (50, 160, 90)
    sw = _text_w(draw, status, small_f) + 18
    sx = W - pad - sw - 8
    draw.rounded_rectangle((sx, pad + 6, sx + sw, pad + 28), 10, fill=sc)
    draw.text((sx + 9, pad + 8), status, font=small_f, fill=(255, 255, 255))

    y = pad + 40
    meta = f"ID {server_id or '—'}  ·  {host or ''}".rstrip(" ·")
    draw.text((tx, y), _truncate(draw, meta, small_f, W - tx - pad), font=small_f, fill=(150, 160, 155))
    used = _paint_tag_chips(
        draw, tag_list, tx, y + 20, tag_f, W - tx - pad,
        fg=(200, 240, 210), bg=(40, 55, 48), outline=accent,
    )

    y = pad + 72 + (used if tag_list else 0)
    if is_off:
        draw.text((tx, y), "无法连接服务器", font=body_f, fill=(255, 140, 140))
        detail = f"上次成功: {last_success_text}" if last_success_text else "请检查地址、端口或服务器是否启动"
        draw.text((tx, y + 32), _truncate(draw, detail, small_f, W - tx - pad), font=small_f, fill=(180, 160, 160))
        return _to_base64(img)

    y += _motd_line(draw, motd, is_off, tx, y, small_f, W - tx - pad, (140, 155, 150))
    draw.text((tx, y), _truncate(draw, f"版本  {server_version}", body_f, 280), font=body_f, fill=(220, 220, 220))
    lx = W - pad - 150
    draw.text((lx, y), f"{latency}ms  {lat_label}", font=body_f, fill=lat_c)

    y += 40
    ratio = plays_online / plays_max if plays_max else 0
    draw.text((pad + 12, y), f"在线玩家  {plays_online}/{plays_max}", font=body_f, fill=(100, 220, 140))
    _draw_progress(draw, pad + 200, y + 8, W - pad * 2 - 200, 12, ratio, (85, 200, 120), (45, 50, 48))

    y += 36
    if lines:
        _paint_chips(draw, lines, pad + 12, y, chip_h, chip_f, (230, 235, 230), (48, 58, 52), player_colors=player_colors)
    else:
        draw.text((pad + 24, y), "暂无玩家在线 — 正是开荒的好时机", font=small_f, fill=(140, 150, 145))
    return _to_base64(img)


# ---------------------------------------------------------------------------
# Dashboard (B)
# ---------------------------------------------------------------------------

async def render_dashboard(
    players_list: list,
    latency: int,
    server_name: str,
    plays_max: int,
    plays_online: int,
    server_version: str,
    icon_base64: Optional[str] = None,
    server_id: Optional[str] = None,
    host: Optional[str] = None,
    online_state: str = "online",
    last_success_text: Optional[str] = None,
    server_name_color: Optional[str] = None,
    player_colors: Optional[Dict[str, str]] = None,
    motd: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> str:
    W, pad = 680, 22
    is_off = online_state != "online"
    lat_c, _ = _latency_tone(latency if not is_off else -1)
    tag_list = normalize_tags(tags)
    title_f = await load_font(30)
    body_f = await load_font(17)
    small_f = await load_font(14)
    metric_f = await load_font(22)
    metric_label_f = await load_font(13)
    chip_f = await load_font(14)
    tag_f = await load_font(13)
    icon, lines, chip_h = await _prep(icon_base64, 80, players_list, chip_f, W - pad * 2 - 20, is_off, 30)
    motd_h = 0 if is_off or not (motd or "").strip() else 20
    tag_h = 26 if tag_list else 0
    player_block = 0 if is_off else (len(lines) * (chip_h + 8) if lines else 26)
    H = (210 if is_off else 250 + motd_h + player_block) + tag_h

    img = Image.new("RGB", (W, H), (18, 20, 28))
    draw = ImageDraw.Draw(img)
    for i in range(H):
        t = i / max(1, H - 1)
        draw.line((0, i, W, i), fill=(int(18 + 12 * t), int(22 + 8 * t), int(34 + 6 * t)))

    card = Image.new("RGBA", (W - 16, H - 16), (30, 34, 48, 245))
    img.paste(card, (8, 8), _rounded_mask(card.size, 20))
    draw = ImageDraw.Draw(img)
    _paste_rounded(img, icon, (pad + 4, pad + 4), 18)

    tx = pad + 4 + 80 + 16
    tc = _title_color(server_name_color, (245, 248, 255))
    draw.text((tx, pad + 6), _truncate(draw, server_name or "未知服务器", title_f, W - tx - pad - 20), font=title_f, fill=tc)
    draw.text(
        (tx, pad + 46),
        _truncate(draw, f"#{server_id or '—'}  {host or ''}", small_f, W - tx - pad),
        font=small_f,
        fill=(140, 150, 175),
    )
    used = _paint_tag_chips(
        draw, tag_list, tx, pad + 66, tag_f, W - tx - pad,
        fg=(180, 200, 255), bg=(36, 42, 62), outline=(100, 130, 200),
    )

    y = pad + 100 + (used if tag_list else 0)
    y += _motd_line(draw, motd, is_off, pad + 4, y - 18, small_f, W - pad * 2, (150, 160, 185))

    if is_off:
        metrics = [
            ("状态", "离线", (255, 100, 110)),
            ("延迟", "—", (160, 160, 170)),
            ("玩家", "—", (160, 160, 170)),
            ("版本", "—", (160, 160, 170)),
        ]
    else:
        metrics = [
            ("状态", "ONLINE", (80, 220, 150)),
            ("延迟", f"{latency}ms", lat_c),
            ("玩家", f"{plays_online}/{plays_max}", (120, 190, 255)),
            ("版本", _truncate(draw, server_version or "—", metric_f, 140), (230, 210, 140)),
        ]

    box_w = (W - pad * 2 - 18) // 4
    for i, (label, value, color) in enumerate(metrics):
        bx = pad + 4 + i * (box_w + 6)
        draw.rounded_rectangle((bx, y, bx + box_w - 4, y + 62), 14, fill=(40, 46, 64))
        draw.text((bx + 12, y + 10), label, font=metric_label_f, fill=(130, 140, 160))
        draw.text((bx + 12, y + 30), value, font=metric_f, fill=color)

    y = y + 78
    if is_off:
        draw.rounded_rectangle((pad, y, W - pad, y + 54), 12, fill=(55, 35, 40))
        detail = f"上次成功: {last_success_text}" if last_success_text else "连接失败 · 可稍后重试 /mc"
        draw.text((pad + 16, y + 16), _truncate(draw, detail, body_f, W - pad * 2 - 32), font=body_f, fill=(255, 180, 180))
        return _to_base64(img)

    ratio = plays_online / plays_max if plays_max else 0
    draw.text((pad + 4, y), "容量", font=small_f, fill=(140, 150, 170))
    _draw_progress(draw, pad + 48, y + 4, W - pad * 2 - 48, 14, ratio, (90, 170, 255), (45, 50, 70))
    y += 32
    draw.text((pad + 4, y), "玩家列表", font=small_f, fill=(140, 150, 170))
    y += 22
    if lines:
        _paint_chips(draw, lines, pad + 4, y, chip_h, chip_f, (230, 235, 255), (48, 56, 78), player_colors=player_colors)
    else:
        draw.text((pad + 8, y), "当前没有玩家在线", font=body_f, fill=(120, 130, 150))
    return _to_base64(img)


# ---------------------------------------------------------------------------
# Inventory (C)
# ---------------------------------------------------------------------------

async def render_inventory(
    players_list: list,
    latency: int,
    server_name: str,
    plays_max: int,
    plays_online: int,
    server_version: str,
    icon_base64: Optional[str] = None,
    server_id: Optional[str] = None,
    host: Optional[str] = None,
    online_state: str = "online",
    last_success_text: Optional[str] = None,
    server_name_color: Optional[str] = None,
    player_colors: Optional[Dict[str, str]] = None,
    motd: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> str:
    W, pad = 620, 18
    is_off = online_state != "online"
    lat_c, _ = _latency_tone(latency if not is_off else -1)
    tag_list = normalize_tags(tags)
    title_f = await load_font(26)
    body_f = await load_font(16)
    small_f = await load_font(14)
    chip_f = await load_font(13)
    tag_f = await load_font(12)
    icon, lines, chip_h = await _prep(icon_base64, 64, players_list, chip_f, W - pad * 2 - 24, is_off, 20)
    motd_h = 0 if is_off or not (motd or "").strip() else 18
    tag_h = 22 if tag_list else 0
    H = 210 + motd_h + tag_h + (0 if is_off else (len(lines) * (chip_h + 6) if lines else 22))

    img = Image.new("RGB", (W, H), (92, 64, 42))
    draw = ImageDraw.Draw(img)
    for yy in range(0, H, 16):
        for xx in range(0, W, 16):
            shade = 8 if ((xx // 16) + (yy // 16)) % 2 == 0 else -8
            draw.rectangle((xx, yy, xx + 15, yy + 15), fill=(92 + shade, 64 + shade, 42 + shade // 2))

    draw.rectangle((10, 10, W - 11, H - 11), fill=(40, 40, 40))
    draw.rectangle((10, 10, W - 11, H - 11), outline=(0, 0, 0), width=3)
    draw.line((12, 12, W - 13, 12), fill=(120, 120, 120))
    draw.line((12, 12, 12, H - 13), fill=(120, 120, 120))
    draw.line((W - 13, 13, W - 13, H - 13), fill=(20, 20, 20))
    draw.line((13, H - 13, W - 13, H - 13), fill=(20, 20, 20))

    draw.rectangle((16, 16, W - 17, 52), fill=(28, 28, 28))
    _paste_rounded(img, icon, (22, 58), 6)

    tc = _title_color(server_name_color, (255, 255, 85) if not is_off else (255, 85, 85))
    draw.text((24, 22), _truncate(draw, server_name or "未知服务器", title_f, W - 120), font=title_f, fill=tc)

    badge_t = "离线" if is_off else "在线"
    bw = _text_w(draw, badge_t, small_f) + 14
    draw.rectangle((W - 18 - bw, 24, W - 18, 44), fill=(0, 0, 0))
    draw.text((W - 18 - bw + 7, 26), badge_t, font=small_f, fill=(255, 85, 85) if is_off else (85, 255, 85))

    tx = 22 + 64 + 14
    y = 62
    draw.text((tx, y), _truncate(draw, f"地址: {host or ''}", small_f, W - tx - 20), font=small_f, fill=(200, 200, 200))
    y += 22
    used = _paint_tag_chips(
        draw, tag_list, tx, y, tag_f, W - tx - 20,
        fg=(255, 255, 170), bg=(50, 50, 40), outline=(100, 100, 60),
    )
    y += used if tag_list else 0
    y += 4 if tag_list else 2
    if is_off:
        draw.text((tx, y), "服务器未响应", font=body_f, fill=(255, 85, 85))
        detail = f"上次成功: {last_success_text}" if last_success_text else "最后查询失败 · 可重试"
        draw.text((tx, y + 26), _truncate(draw, detail, small_f, W - tx - 20), font=small_f, fill=(170, 170, 170))
        return _to_base64(img)

    y += _motd_line(draw, motd, is_off, tx, y, small_f, W - tx - 20, (180, 180, 160))
    draw.text((tx, y), _truncate(draw, f"版本: {server_version}", body_f, 260), font=body_f, fill=(220, 220, 220))
    draw.text((tx + 270, y), f"延迟: {latency}ms", font=body_f, fill=lat_c)
    y += 28
    ratio = plays_online / plays_max if plays_max else 0
    draw.text((tx, y), f"玩家: {plays_online}/{plays_max}", font=body_f, fill=(85, 255, 85))
    bar_x, bar_y, bar_w, bar_h = tx + 140, y + 4, W - tx - 160, 14
    draw.rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), fill=(20, 20, 20), outline=(0, 0, 0))
    fw = int(bar_w * ratio)
    if fw:
        c = (85, 255, 85) if ratio < 0.8 else (255, 170, 0) if ratio < 0.95 else (255, 85, 85)
        draw.rectangle((bar_x + 1, bar_y + 1, bar_x + max(2, fw) - 1, bar_y + bar_h - 1), fill=c)

    y = 150 + motd_h + tag_h
    draw.text((22, y), "在线名单", font=small_f, fill=(170, 170, 170))
    y += 22
    if lines:
        for line in lines:
            xx = 22
            for name in line:
                custom = None
                if player_colors and not name.startswith("+"):
                    from ..get_img import _lookup_player_color
                    custom = _lookup_player_color(name, player_colors)
                fg = custom or (230, 230, 230)
                nw = _text_w(draw, name, chip_f) + 14
                draw.rectangle((xx, y, xx + nw, y + chip_h), fill=(55, 55, 55), outline=(20, 20, 20))
                draw.line((xx + 1, y + 1, xx + nw - 2, y + 1), fill=(90, 90, 90))
                draw.text((xx + 7, y + 4), name, font=chip_f, fill=fg)
                xx += nw + 6
            y += chip_h + 6
    else:
        draw.text((28, y), "空空如也…", font=body_f, fill=(140, 140, 140))
    return _to_base64(img)


# ---------------------------------------------------------------------------
# Soft light (D)
# ---------------------------------------------------------------------------

async def render_soft(
    players_list: list,
    latency: int,
    server_name: str,
    plays_max: int,
    plays_online: int,
    server_version: str,
    icon_base64: Optional[str] = None,
    server_id: Optional[str] = None,
    host: Optional[str] = None,
    online_state: str = "online",
    last_success_text: Optional[str] = None,
    server_name_color: Optional[str] = None,
    player_colors: Optional[Dict[str, str]] = None,
    motd: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> str:
    W, pad = 640, 22
    is_off = online_state != "online"
    lat_c, lat_label = _latency_tone(latency if not is_off else -1)
    if lat_c == (85, 220, 120):
        lat_c = (20, 150, 80)
    elif lat_c == (255, 90, 90):
        lat_c = (200, 50, 50)
    tag_list = normalize_tags(tags)

    title_f = await load_font(28)
    body_f = await load_font(17)
    small_f = await load_font(14)
    chip_f = await load_font(14)
    tag_f = await load_font(13)
    icon, lines, chip_h = await _prep(icon_base64, 68, players_list, chip_f, W - pad * 2 - 16, is_off)
    motd_h = 0 if is_off or not (motd or "").strip() else 20
    tag_h = 26 if tag_list else 0
    H = 220 + motd_h + tag_h + (0 if is_off else (len(lines) * (chip_h + 8) if lines else 24))

    img = Image.new("RGB", (W, H), (245, 247, 250))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((14, 16, W - 10, H - 8), 18, fill=(0, 0, 0, 40))
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    img = Image.alpha_composite(img.convert("RGBA"), shadow).convert("RGB")
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((10, 10, W - 14, H - 14), 18, fill=(255, 255, 255), outline=(230, 234, 240), width=1)

    strip = (76, 175, 120) if not is_off else (230, 100, 100)
    draw.rounded_rectangle((10, 10, W - 14, 18), 18, fill=strip)
    draw.rectangle((10, 18, W - 14, 28), fill=strip)
    _paste_rounded(img, icon, (pad + 4, pad + 22), 16)

    tx = pad + 4 + 68 + 14
    tc = _title_color(server_name_color, (30, 35, 45))
    draw.text((tx, pad + 24), _truncate(draw, server_name or "未知服务器", title_f, W - tx - pad - 80), font=title_f, fill=tc)

    status = "离线" if is_off else "在线"
    sc_bg = (255, 230, 230) if is_off else (230, 250, 238)
    sc_fg = (190, 50, 50) if is_off else (25, 140, 80)
    sw = _text_w(draw, status, small_f) + 16
    sx = W - pad - sw - 8
    draw.rounded_rectangle((sx, pad + 30, sx + sw, pad + 52), 12, fill=sc_bg)
    draw.text((sx + 8, pad + 33), status, font=small_f, fill=sc_fg)

    draw.text(
        (tx, pad + 62),
        _truncate(draw, f"ID {server_id or '—'} · {host or ''}", small_f, W - tx - pad),
        font=small_f,
        fill=(120, 128, 140),
    )
    used = _paint_tag_chips(
        draw, tag_list, tx, pad + 82, tag_f, W - tx - pad,
        fg=(40, 100, 80), bg=(230, 245, 238), outline=(140, 200, 170),
    )

    y = pad + 100 + (used if tag_list else 0)
    if is_off:
        draw.rounded_rectangle((pad, y, W - pad - 8, y + 56), 12, fill=(255, 245, 245))
        draw.text((pad + 14, y + 10), "暂时连不上这台服务器", font=body_f, fill=(180, 60, 60))
        detail = f"上次成功: {last_success_text}" if last_success_text else "不会影响其他服务器的查询结果"
        draw.text((pad + 14, y + 34), _truncate(draw, detail, small_f, W - pad * 2 - 28), font=small_f, fill=(150, 120, 120))
        return _to_base64(img)

    y += _motd_line(draw, motd, is_off, pad, y - 4, small_f, W - pad * 2 - 8, (110, 120, 130))
    half = (W - pad * 2 - 16) // 2
    draw.rounded_rectangle((pad, y, pad + half, y + 58), 12, fill=(246, 248, 252))
    draw.rounded_rectangle((pad + half + 12, y, pad + half * 2 + 12, y + 58), 12, fill=(246, 248, 252))
    draw.text((pad + 14, y + 10), "版本", font=small_f, fill=(130, 138, 150))
    draw.text((pad + 14, y + 30), _truncate(draw, server_version or "—", body_f, half - 28), font=body_f, fill=(40, 45, 55))
    draw.text((pad + half + 26, y + 10), "延迟", font=small_f, fill=(130, 138, 150))
    draw.text((pad + half + 26, y + 30), f"{latency}ms · {lat_label}", font=body_f, fill=lat_c)

    y += 72
    ratio = plays_online / plays_max if plays_max else 0
    draw.text((pad, y), f"在线  {plays_online}/{plays_max}", font=body_f, fill=(40, 45, 55))
    _draw_progress(draw, pad + 140, y + 6, W - pad * 2 - 148, 12, ratio, (76, 175, 120), (230, 234, 240))
    y += 32
    if lines:
        _paint_chips(draw, lines, pad, y, chip_h, chip_f, (50, 60, 70), (240, 243, 247), player_colors=player_colors)
    else:
        draw.text((pad + 4, y), "暂时没有玩家，来做第一个吧", font=small_f, fill=(150, 158, 170))
    return _to_base64(img)


# ---------------------------------------------------------------------------
# Compact (E)
# ---------------------------------------------------------------------------

async def render_compact(
    players_list: list,
    latency: int,
    server_name: str,
    plays_max: int,
    plays_online: int,
    server_version: str,
    icon_base64: Optional[str] = None,
    server_id: Optional[str] = None,
    host: Optional[str] = None,
    online_state: str = "online",
    last_success_text: Optional[str] = None,
    server_name_color: Optional[str] = None,
    player_colors: Optional[Dict[str, str]] = None,
    motd: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> str:
    W = 600
    is_off = online_state != "online"
    has_motd = bool((motd or "").strip()) and not is_off
    tag_list = normalize_tags(tags)
    has_tags = bool(tag_list)
    H = (112 if not is_off else 96) + (18 if has_motd else 0) + (20 if has_tags else 0)
    pad = 14
    title_f = await load_font(22)
    body_f = await load_font(14)
    small_f = await load_font(13)
    tag_f = await load_font(12)
    icon = await fetch_icon(icon_base64)
    icon = icon.resize((56, 56), Image.Resampling.NEAREST)
    lat_c, _ = _latency_tone(latency if not is_off else -1)

    img = Image.new("RGB", (W, H), (24, 26, 30))
    draw = ImageDraw.Draw(img)
    accent = (255, 90, 90) if is_off else (70, 200, 120)
    draw.rounded_rectangle((1, 1, W - 2, H - 2), 12, outline=(45, 50, 56), width=1)
    draw.rectangle((0, 10, 5, H - 10), fill=accent)
    _paste_rounded(img, icon, (pad + 4, (H - 56) // 2), 10)

    tx = pad + 4 + 56 + 12
    tc = _title_color(server_name_color, (240, 242, 245))
    draw.text((tx, 12), _truncate(draw, server_name or "未知服务器", title_f, W - tx - 90), font=title_f, fill=tc)

    status = "OFF" if is_off else "ON"
    sc = (200, 70, 70) if is_off else (40, 150, 90)
    sw = _text_w(draw, status, small_f) + 12
    draw.rounded_rectangle((W - pad - sw, 14, W - pad, 32), 8, fill=sc)
    draw.text((W - pad - sw + 6, 15), status, font=small_f, fill=(255, 255, 255))

    # meta line (ID + host) then tags
    meta_host = f"#{server_id or '—'}  {host or ''}".strip()
    draw.text((tx, 38), _truncate(draw, meta_host, small_f, W - tx - pad), font=small_f, fill=(140, 150, 160))
    y = 56
    used = _paint_tag_chips(
        draw, tag_list, tx, y, tag_f, W - tx - pad,
        fg=(180, 230, 200), bg=(36, 48, 42), outline=accent,
    )
    y += used if has_tags else 0

    if is_off:
        detail = "连接失败"
        if last_success_text:
            detail = f"上次成功 {last_success_text}"
        draw.text((tx, y + 2), _truncate(draw, detail, body_f, W - tx - pad), font=body_f, fill=(180, 140, 140))
        return _to_base64(img)

    if has_motd:
        draw.text((tx, y), _truncate(draw, (motd or "").strip(), small_f, W - tx - pad), font=small_f, fill=(150, 160, 170))
        y += 16

    players = list(players_list or [])
    players_preview = "、".join(players[:4])
    if len(players) > 4:
        players_preview += f" 等{plays_online}人"
    elif not players:
        players_preview = "无人在线"
    meta1 = f"{server_version}  ·  {latency}ms"
    draw.text((tx, y), _truncate(draw, meta1, body_f, W - tx - pad), font=body_f, fill=lat_c if latency >= 200 else (170, 178, 186))
    draw.text((tx, y + 18), _truncate(draw, f"{plays_online}/{plays_max}  {players_preview}", body_f, W - tx - pad), font=body_f, fill=(200, 205, 210))

    ratio = plays_online / plays_max if plays_max else 0
    _draw_progress(draw, tx, H - 14, W - tx - pad, 6, ratio, (70, 190, 120), (40, 44, 50))
    return _to_base64(img)
