"""AstrBot / 群角色解析。

优先级：
1. OneBot raw_message.sender.role (owner|admin|member)
2. await event.get_group() 的 group_owner / group_admins
3. 已填充的 message_obj.group
4. event.is_admin() 仅表示 AstrBot 系统管理员
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set


def _norm_id(value: Any) -> str:
    return str(value or "").strip()


def _role_from_raw_message(raw_message: Any) -> Optional[str]:
    if raw_message is None:
        return None
    if isinstance(raw_message, dict):
        sender = raw_message.get("sender")
        if isinstance(sender, dict):
            role = sender.get("role")
            if role is not None:
                return str(role).strip().lower()
        return None
    sender = getattr(raw_message, "sender", None)
    if sender is None:
        return None
    if isinstance(sender, dict):
        role = sender.get("role")
    else:
        role = getattr(sender, "role", None)
    if role is None:
        return None
    return str(role).strip().lower()


def _ids_from_group_obj(group: Any) -> tuple[str, Set[str]]:
    if group is None:
        return "", set()
    owner = _norm_id(getattr(group, "group_owner", None) or (group.get("group_owner") if isinstance(group, dict) else ""))
    admins_raw = getattr(group, "group_admins", None)
    if admins_raw is None and isinstance(group, dict):
        admins_raw = group.get("group_admins")
    admin_set: Set[str] = set()
    for a in admins_raw or []:
        s = _norm_id(a)
        if s:
            admin_set.add(s)
    return owner, admin_set


def roles_from_raw_and_group(
    *,
    sender_id: str,
    raw_message: Any = None,
    group: Any = None,
    astrbot_admin: bool = False,
) -> Dict[str, bool]:
    """纯函数：由 raw/group/is_admin 推导角色。供测试与 resolve_roles 共用。"""
    sender_id = _norm_id(sender_id)
    is_owner = False
    is_group_admin = False

    raw_role = _role_from_raw_message(raw_message)
    if raw_role in {"owner", "group_owner"}:
        is_owner = True
        is_group_admin = True
    elif raw_role in {"admin", "administrator", "group_admin"}:
        is_group_admin = True

    owner_id, admin_set = _ids_from_group_obj(group)
    if sender_id and owner_id and sender_id == owner_id:
        is_owner = True
        is_group_admin = True
    if sender_id and sender_id in admin_set:
        is_group_admin = True

    return {
        "astrbot_admin": bool(astrbot_admin),
        "group_owner": is_owner,
        "group_admin": is_group_admin,
    }


async def resolve_roles(event: Any) -> Dict[str, bool]:
    """解析消息发送者角色。"""
    sender_id = ""
    if hasattr(event, "get_sender_id"):
        try:
            sender_id = _norm_id(event.get_sender_id())
        except Exception:
            sender_id = ""
    if not sender_id:
        sender_id = _norm_id(getattr(event, "sender_id", ""))

    astrbot_admin = False
    if hasattr(event, "is_admin"):
        try:
            astrbot_admin = bool(event.is_admin())
        except Exception:
            astrbot_admin = False
    else:
        astrbot_admin = str(getattr(event, "role", "") or "").lower() == "admin"

    message_obj = getattr(event, "message_obj", None)
    raw_message = getattr(message_obj, "raw_message", None) if message_obj is not None else None
    group = getattr(message_obj, "group", None) if message_obj is not None else None

    # 优先 raw；若无 owner/admin 再尝试 get_group
    roles = roles_from_raw_and_group(
        sender_id=sender_id,
        raw_message=raw_message,
        group=group,
        astrbot_admin=astrbot_admin,
    )

    if not roles["group_owner"] and not roles["group_admin"] and hasattr(event, "get_group"):
        try:
            fetched = await event.get_group()
        except Exception:
            fetched = None
        if fetched is not None:
            extra = roles_from_raw_and_group(
                sender_id=sender_id,
                raw_message=None,
                group=fetched,
                astrbot_admin=astrbot_admin,
            )
            roles["group_owner"] = roles["group_owner"] or extra["group_owner"]
            roles["group_admin"] = roles["group_admin"] or extra["group_admin"]

    return roles


async def can_manage_group_feature(event: Any) -> bool:
    """系统管理员或群主或群管。"""
    roles = await resolve_roles(event)
    return bool(roles["astrbot_admin"] or roles["group_owner"] or roles["group_admin"])


def extract_sender_level(event: Any) -> int:
    """从 event 提取群等级（兼容 OneBot sender.level）。"""
    import re

    level_candidates = []
    message_obj = getattr(event, "message_obj", None)
    sender = getattr(message_obj, "sender", None) if message_obj is not None else None
    if sender is not None:
        level_candidates.append(getattr(sender, "level", None))
        level_candidates.append(getattr(sender, "group_level", None))
        if isinstance(sender, dict):
            level_candidates.append(sender.get("level"))

    raw_message = getattr(message_obj, "raw_message", None) if message_obj is not None else None
    if isinstance(raw_message, dict):
        sender_obj = raw_message.get("sender")
        if isinstance(sender_obj, dict):
            level_candidates.append(sender_obj.get("level"))

    for raw_level in level_candidates:
        if raw_level is None:
            continue
        if isinstance(raw_level, (int, float)):
            return int(raw_level)
        s = str(raw_level)
        m = re.search(r"\d+", s)
        if m:
            try:
                return int(m.group(0))
            except Exception:
                continue
    return 0


async def can_use_mcq(
    event: Any,
    *,
    permission_enabled: bool = True,
    whitelist: Optional[list] = None,
    allow_astrbot_admin: bool = True,
    allow_group_owner: bool = True,
    allow_group_admin: bool = True,
    min_group_level: int = 90,
) -> bool:
    """/mcq 权限：白名单 / 系统管理员 / 群主 / 群管 / 等级。"""
    if not permission_enabled:
        return True

    sender_id = ""
    if hasattr(event, "get_sender_id"):
        try:
            sender_id = _norm_id(event.get_sender_id())
        except Exception:
            sender_id = ""

    wl = {_norm_id(x) for x in (whitelist or []) if _norm_id(x)}
    if sender_id and sender_id in wl:
        return True

    roles = await resolve_roles(event)
    if allow_astrbot_admin and roles["astrbot_admin"]:
        return True
    if allow_group_owner and roles["group_owner"]:
        return True
    if allow_group_admin and roles["group_admin"]:
        return True

    if min_group_level > 0 and extract_sender_level(event) >= min_group_level:
        return True

    return False
