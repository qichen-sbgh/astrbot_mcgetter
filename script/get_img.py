"""
Default server-status card renderer — Design F · Neon Glass.
"""

from __future__ import annotations

import base64
import hashlib
import io
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

RESOURCE_DIR = Path(__file__).resolve().parent.parent / "resource"
FONT_PATH = RESOURCE_DIR / "msyh.ttf"
DEFAULT_ICON_PATH = RESOURCE_DIR / "default_icon.png"

# 解码后的服务器图标内存 LRU 缓存（进程内；重启清空）
_ICON_CACHE_MAX = 64
_icon_cache: "OrderedDict[str, Image.Image]" = OrderedDict()


# ---------------------------------------------------------------------------
# Font / icon
# ---------------------------------------------------------------------------

async def load_font(font_size: int):
    font_paths = [
        FONT_PATH,
        Path("msyh.ttf"),
        Path("/usr/share/fonts/zh_CN/msyh.ttf"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(str(path), font_size)
        except OSError:
            continue
    try:
        return ImageFont.load_default().font_variant(size=font_size)
    except Exception:
        return ImageFont.load_default()


def _icon_cache_get(key: str) -> Optional[Image.Image]:
    cached = _icon_cache.get(key)
    if cached is None:
        return None
    _icon_cache.move_to_end(key)
    return cached.copy()


def _icon_cache_put(key: str, img: Image.Image) -> None:
    if key in _icon_cache:
        _icon_cache.move_to_end(key)
    _icon_cache[key] = img.copy()
    while len(_icon_cache) > _ICON_CACHE_MAX:
        _icon_cache.popitem(last=False)


async def fetch_icon(icon_base64: Optional[str] = None) -> Image.Image:
    """Decode server icon (with in-memory LRU); fall back to bundled default icon."""
    if icon_base64:
        try:
            raw = icon_base64.split(",", 1)[1] if "," in icon_base64 else icon_base64
            cache_key = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]
            cached = _icon_cache_get(cache_key)
            if cached is not None:
                return cached
            img = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGBA")
            _icon_cache_put(cache_key, img)
            return img.copy()
        except Exception as e:
            print(f"Base64图标解码失败: {e}")

    # 默认图标：固定 key，避免反复读盘
    default_key = "__default__"
    cached_default = _icon_cache_get(default_key)
    if cached_default is not None:
        return cached_default

    if DEFAULT_ICON_PATH.exists():
        try:
            img = Image.open(DEFAULT_ICON_PATH).convert("RGBA")
            _icon_cache_put(default_key, img)
            return img.copy()
        except Exception:
            pass

    # solid fallback
    img = Image.new("RGBA", (64, 64), (40, 50, 70, 255))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, 59, 59), 12, fill=(0, 180, 150, 255))
    _icon_cache_put(default_key, img)
    return img.copy()


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _text_h(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[3] - box[1]


def _truncate(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
    if _text_w(draw, text, font) <= max_w:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        if _text_w(draw, text[:mid] + ell, font) <= max_w:
            lo = mid + 1
        else:
            hi = mid
    return text[: max(0, lo - 1)] + ell


def _rounded_mask(size: Tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return mask


def _paste_rounded(base: Image.Image, icon: Image.Image, xy: Tuple[int, int], radius: int = 16) -> None:
    icon = icon.convert("RGBA")
    base.paste(icon, xy, _rounded_mask(icon.size, radius))


def _latency_tone(ms: int) -> Tuple[Tuple[int, int, int], str]:
    if ms < 0:
        return (160, 160, 160), "不可用"
    if ms < 80:
        return (85, 220, 120), "优秀"
    if ms < 150:
        return (180, 220, 90), "良好"
    if ms < 250:
        return (255, 180, 60), "一般"
    return (255, 90, 90), "较高"


def _draw_progress(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    ratio: float,
    fill: Tuple[int, int, int],
    track: Tuple[int, int, int] = (30, 36, 50),
) -> None:
    ratio = max(0.0, min(1.0, ratio))
    draw.rounded_rectangle((x, y, x + w, y + h), h // 2, fill=track)
    if ratio <= 0:
        return
    fw = max(h, int(w * ratio))
    color = fill
    if ratio >= 0.9:
        color = (255, 100, 90)
    elif ratio >= 0.7:
        color = (255, 170, 70)
    draw.rounded_rectangle((x, y, x + fw, y + h), h // 2, fill=color)


def _wrap_chips(
    draw: ImageDraw.ImageDraw,
    names: List[str],
    font,
    max_w: int,
    max_lines: int = 3,
) -> Tuple[List[List[str]], int]:
    if not names:
        return [], 0
    chip_h = _text_h(draw, "Ag", font) + 10
    gap = 8
    lines: List[List[str]] = [[]]
    cur_w = 0
    for i, name in enumerate(names):
        nw = _text_w(draw, name, font) + 16
        need = nw if not lines[-1] else nw + gap
        if cur_w + need > max_w and lines[-1]:
            if len(lines) >= max_lines:
                remain = len(names) - i
                plus = f"+{remain}"
                pw = _text_w(draw, plus, font) + 16
                last = lines[-1]
                while last and cur_w + gap + pw > max_w:
                    dropped = last.pop()
                    cur_w -= _text_w(draw, dropped, font) + 16 + (gap if last else 0)
                    remain += 1
                    plus = f"+{remain}"
                    pw = _text_w(draw, plus, font) + 16
                last.append(plus)
                break
            lines.append([])
            cur_w = 0
            need = nw
        lines[-1].append(name)
        cur_w += need
    return lines, chip_h


def _parse_rgb(color: Optional[str]) -> Optional[Tuple[int, int, int]]:
    """Parse #RGB / #RRGGBB / RRGGBB into RGB."""
    if not color or not isinstance(color, str):
        return None
    s = color.strip()
    if s.startswith("#"):
        s = s[1:]
    try:
        if len(s) == 3 and all(c in "0123456789abcdefABCDEF" for c in s):
            return int(s[0] * 2, 16), int(s[1] * 2, 16), int(s[2] * 2, 16)
        if len(s) == 6 and all(c in "0123456789abcdefABCDEF" for c in s):
            return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return None
    return None


def _lookup_player_color(
    name: str,
    player_colors: Optional[Dict[str, str]],
) -> Optional[Tuple[int, int, int]]:
    if not player_colors or name.startswith("+"):
        return None
    if name in player_colors:
        return _parse_rgb(player_colors[name])
    lower = name.lower()
    for key, value in player_colors.items():
        if key.lower() == lower:
            return _parse_rgb(value)
    return None


def _chip_bg_from_fg(fg: Tuple[int, int, int]) -> Tuple[int, int, int]:
    return (
        max(16, min(70, fg[0] // 4 + 12)),
        max(16, min(70, fg[1] // 4 + 12)),
        max(16, min(70, fg[2] // 4 + 12)),
    )


def _paint_chips(
    draw: ImageDraw.ImageDraw,
    lines: List[List[str]],
    x: int,
    y: int,
    chip_h: int,
    font,
    fg: Tuple[int, int, int],
    bg: Tuple[int, int, int],
    gap: int = 8,
    player_colors: Optional[Dict[str, str]] = None,
) -> None:
    yy = y
    for line in lines:
        xx = x
        for name in line:
            custom = _lookup_player_color(name, player_colors)
            text_fg = custom or fg
            chip_bg = _chip_bg_from_fg(custom) if custom else bg
            nw = _text_w(draw, name, font) + 16
            draw.rounded_rectangle((xx, yy, xx + nw, yy + chip_h), chip_h // 2, fill=chip_bg)
            draw.text((xx + 8, yy + 4), name, font=font, fill=text_fg)
            xx += nw + gap
        yy += chip_h + gap


def _to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ---------------------------------------------------------------------------
# Design F · Neon Glass
# ---------------------------------------------------------------------------

async def generate_server_info_image(
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
) -> str:
    """
    Render neon-glass status card and return PNG base64.

    online_state: "online" | "offline"
    server_name_color: optional #RRGGBB for server title
    player_colors: optional {player_name: #RRGGBB} applied on player chips
    motd: optional plain-text server description (online only)
    """
    W = 660
    pad = 22
    is_off = online_state != "online"
    neon = (0, 255, 200) if not is_off else (255, 80, 140)
    lat_c, lat_label = _latency_tone(latency if not is_off else -1)
    title_color = _parse_rgb(server_name_color) or (240, 250, 255)
    motd_text = (motd or "").strip() if not is_off else ""

    title_f = await load_font(30)
    body_f = await load_font(17)
    small_f = await load_font(14)
    chip_f = await load_font(14)

    icon = await fetch_icon(icon_base64)
    icon = icon.resize((76, 76), Image.Resampling.NEAREST)

    # measure player chips
    tmp = Image.new("RGB", (10, 10))
    dtmp = ImageDraw.Draw(tmp)
    show = [] if is_off else list(players_list or [])[:22]
    lines, chip_h = _wrap_chips(dtmp, show, chip_f, W - pad * 2 - 24, max_lines=3)
    player_block = 0 if is_off else (len(lines) * (chip_h + 8) if lines else 24)
    motd_block = 22 if motd_text else 0
    H = (210 if is_off else 240 + motd_block + player_block)

    # deep background + soft glow
    img = Image.new("RGB", (W, H), (8, 10, 18))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-40, -60, 280, 220), fill=(*neon, 35))
    gd.ellipse((W - 260, H - 200, W + 40, H + 40), fill=(80, 60, 255, 28))
    glow = glow.filter(ImageFilter.GaussianBlur(30))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(img)

    # glass panel
    panel = Image.new("RGBA", (W - 20, H - 20), (20, 24, 40, 180))
    img.paste(panel, (10, 10), _rounded_mask(panel.size, 22))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((10, 10, W - 11, H - 11), 22, outline=neon, width=2)

    # icon + neon ring
    _paste_rounded(img, icon, (pad + 6, pad + 8), 18)
    draw.rounded_rectangle((pad + 4, pad + 6, pad + 6 + 80, pad + 6 + 80), 20, outline=neon, width=1)

    tx = pad + 6 + 76 + 18
    name = _truncate(draw, server_name or "未知服务器", title_f, W - tx - pad - 20)
    draw.text((tx, pad + 12), name, font=title_f, fill=title_color)

    # meta: ID // host
    id_part = f"ID {server_id}" if server_id not in (None, "") else "ID —"
    host_part = host or ""
    if host_part:
        meta = f"{id_part}  //  {host_part}"
    else:
        meta = id_part
    draw.text(
        (tx, pad + 52),
        _truncate(draw, meta, small_f, W - tx - pad),
        font=small_f,
        fill=(120, 150, 170),
    )

    y = pad + 100
    if is_off:
        draw.rounded_rectangle((pad + 4, y, W - pad - 4, y + 72), 14, fill=(40, 18, 30))
        draw.text((pad + 20, y + 12), "SIGNAL LOST", font=title_f, fill=neon)
        detail = "服务器无响应 · 其他卡片仍可正常展示"
        if last_success_text:
            detail = f"上次成功: {last_success_text}"
        draw.text((pad + 20, y + 48), _truncate(draw, detail, small_f, W - pad * 2 - 40), font=small_f, fill=(200, 160, 180))
        return _to_base64(img)

    # MOTD one-liner under header
    if motd_text:
        draw.text(
            (pad + 8, y - 6),
            _truncate(draw, motd_text, small_f, W - pad * 2 - 16),
            font=small_f,
            fill=(150, 180, 195),
        )
        y += motd_block

    # stat tiles
    stats = [
        (f"{int(latency)}ms", lat_label, lat_c),
        (f"{plays_online}/{plays_max}", "PLAYERS", (0, 200, 255)),
        (_truncate(draw, server_version or "—", body_f, 160), "VERSION", (220, 180, 255)),
    ]
    sw = (W - pad * 2 - 20) // 3
    for i, (val, lab, col) in enumerate(stats):
        bx = pad + 4 + i * (sw + 8)
        draw.rounded_rectangle((bx, y, bx + sw, y + 56), 12, fill=(16, 22, 36), outline=col, width=1)
        draw.text((bx + 12, y + 8), lab, font=small_f, fill=(120, 140, 160))
        draw.text((bx + 12, y + 28), val, font=body_f, fill=col)

    y += 72
    ratio = (plays_online / plays_max) if plays_max else 0.0
    _draw_progress(draw, pad + 4, y, W - pad * 2 - 8, 8, ratio, neon, (30, 36, 50))
    y += 22

    if lines:
        _paint_chips(
            draw, lines, pad + 4, y, chip_h, chip_f,
            (220, 255, 250), (24, 40, 48),
            player_colors=player_colors,
        )
    else:
        draw.text((pad + 8, y), "EMPTY LOBBY", font=body_f, fill=(100, 130, 140))

    return _to_base64(img)
