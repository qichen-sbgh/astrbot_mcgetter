from pathlib import Path
from typing import Dict, List, Optional, Tuple
from .get_img import generate_server_info_image
from .themes import (
    DEFAULT_THEME,
    is_builtin,
    list_builtin_entries,
    normalize_theme_id,
    render_builtin,
)
from astrbot.api.star import StarTools
import importlib.util
import sys
from astrbot.api import logger

# 数据目录和配置文件路径（全局 template.txt 仅作旧配置回退）
DATA_DIR = Path(StarTools.get_data_dir("astrbot_mcgetter"))
CONFIG_FILE = DATA_DIR / "template.txt"
TEMPLATE_DIR = DATA_DIR / "template"

# 确保模板目录存在
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)


def list_custom_template_names() -> List[str]:
    """List custom template module stems under data/template/*.py."""
    names: List[str] = []
    try:
        if TEMPLATE_DIR.is_dir():
            for p in sorted(TEMPLATE_DIR.glob("*.py")):
                if p.name.startswith("_"):
                    continue
                names.append(p.stem)
    except Exception as e:
        logger.warning(f"列举自定义模板失败: {e}")
    return names


def format_template_help(current: str) -> str:
    """Human-readable template list for /mctem."""
    cur = normalize_theme_id(current) if is_builtin(current or "") else (current or DEFAULT_THEME)
    lines = [
        f"当前本群主题：{cur}",
        "",
        "内置主题：",
    ]
    for tid, label in list_builtin_entries():
        mark = " ← 当前" if tid == cur or (cur == "default" and tid == "neon") else ""
        lines.append(f"  · {tid}  {label}{mark}")

    customs = list_custom_template_names()
    lines.append("")
    if customs:
        lines.append("自定义模板（数据目录 template/*.py）：")
        for name in customs:
            mark = " ← 当前" if name == cur else ""
            lines.append(f"  · {name}{mark}")
    else:
        lines.append("自定义模板：暂无（可将 draw_image 脚本放入数据目录 template/）")

    lines.append("")
    lines.append("切换：/mctem <主题名>")
    lines.append("列表：/mctem 或 /mctem list")
    return "\n".join(lines)


def resolve_template_name(name: str) -> Tuple[bool, str, str]:
    """
    Validate template name.
    Returns (ok, resolved_name, error_message).
    """
    raw = (name or "").strip()
    if not raw:
        return False, "", "请指定模板名称，或使用 /mctem list 查看可用主题"
    low = raw.lower()
    if is_builtin(low):
        return True, normalize_theme_id(low), ""
    # custom file
    template_file = TEMPLATE_DIR / f"{raw}.py"
    if template_file.is_file():
        return True, raw, ""
    # also try lower-case stem match
    for custom in list_custom_template_names():
        if custom.lower() == low:
            return True, custom, ""
    builtins = ", ".join(tid for tid, _ in list_builtin_entries())
    return False, "", f"未知主题「{raw}」。内置：{builtins}。也可用 /mctem list 查看。"


async def get_img(
    players_list: List[str],
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
    template: Optional[str] = None,
) -> str:
    """
    生成服务器信息图片并返回 base64 字符串。
    template: 群维度主题 id；缺省时回退全局 template.txt / neon。
    """
    config = (template or "").strip() or read_config()
    config_low = config.lower()

    render_kwargs = dict(
        players_list=players_list,
        latency=latency,
        server_name=server_name,
        plays_max=plays_max,
        plays_online=plays_online,
        server_version=server_version,
        icon_base64=icon_base64,
        server_id=server_id,
        host=host,
        online_state=online_state,
        last_success_text=last_success_text,
        server_name_color=server_name_color,
        player_colors=player_colors,
        motd=motd,
    )

    # 1) 自定义模板优先（同名可覆盖内置）
    custom_file = TEMPLATE_DIR / f"{config}.py"
    if not custom_file.is_file():
        # case-insensitive custom match
        for name in list_custom_template_names():
            if name.lower() == config_low:
                custom_file = TEMPLATE_DIR / f"{name}.py"
                config = name
                break

    if custom_file.is_file():
        try:
            result = await _run_custom_template(config, custom_file, render_kwargs)
            if isinstance(result, str) and result:
                return result
        except Exception as e:
            logger.info(f"加载或执行自定义模板 {config} 出错：{e}，回退内置/默认。")

    # 2) 内置主题
    if is_builtin(config_low):
        try:
            result = await render_builtin(config_low, **render_kwargs)
            if isinstance(result, str) and result:
                return result
        except Exception as e:
            logger.info(f"内置主题 {config} 渲染失败：{e}，使用 neon。")

    # 3) 最终回退 neon
    return await generate_server_info_image(**render_kwargs)


async def _run_custom_template(config: str, template_file: Path, render_kwargs: dict) -> Optional[str]:
    module_name = f"astrbot_mcgetter_tpl_{config}"
    spec = importlib.util.spec_from_file_location(module_name, template_file)
    if not spec or not spec.loader:
        logger.info(f"无法加载 {template_file} 的模块规格。")
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    if not hasattr(module, "draw_image"):
        logger.info(f"模板 {config} 缺少 'draw_image' 函数。")
        return None

    # 自定义模板保持旧签名兼容
    server_id = render_kwargs.get("server_id")
    server_name = render_kwargs.get("server_name") or ""
    display_name = server_name if not server_id else f"[{server_id}]{server_name}"
    result = await module.draw_image(
        players_list=render_kwargs.get("players_list") or [],
        latency=render_kwargs.get("latency") or 0,
        server_name=display_name,
        plays_max=render_kwargs.get("plays_max") or 0,
        plays_online=render_kwargs.get("plays_online") or 0,
        server_version=render_kwargs.get("server_version") or "",
        icon_base64=render_kwargs.get("icon_base64"),
    )
    if not isinstance(result, str):
        logger.info(f"模板 {config} 返回的 base64 字符串无效。")
        return None
    return result


def write_config(template_name: str) -> bool:
    """将模板名称写入全局配置文件（兼容旧逻辑；新逻辑请写群 JSON）。"""
    try:
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            f.write(template_name)
        logger.info(f"成功将 '{template_name}' 写入 {CONFIG_FILE}")
        return True
    except Exception as e:
        logger.info(f"写入 {CONFIG_FILE} 出错：{e}")
        return False


def read_config() -> str:
    """从全局配置文件读取模板名称；不存在则返回 default/neon。"""
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            value = f.read().strip()
            return value or DEFAULT_THEME
    except FileNotFoundError:
        return DEFAULT_THEME
    except Exception as e:
        logger.info(f"读取 {CONFIG_FILE} 出错：{e}")
        return DEFAULT_THEME
