from __future__ import annotations

import asyncio
from types import SimpleNamespace

from script.permission import (
    can_manage_group_feature,
    can_use_mcq,
    resolve_roles,
    roles_from_raw_and_group,
)


def test_raw_owner_admin_member():
    owner = roles_from_raw_and_group(
        sender_id="100",
        raw_message={"sender": {"role": "owner", "user_id": "100"}},
        astrbot_admin=False,
    )
    assert owner["group_owner"] and owner["group_admin"]
    assert not owner["astrbot_admin"]

    admin = roles_from_raw_and_group(
        sender_id="200",
        raw_message={"sender": {"role": "admin"}},
        astrbot_admin=False,
    )
    assert admin["group_admin"] and not admin["group_owner"]

    member = roles_from_raw_and_group(
        sender_id="300",
        raw_message={"sender": {"role": "member"}},
        astrbot_admin=False,
    )
    assert not member["group_owner"] and not member["group_admin"]


def test_get_group_style_ids():
    group = SimpleNamespace(group_owner="1", group_admins=["2", "3"])
    r = roles_from_raw_and_group(sender_id="2", group=group, astrbot_admin=False)
    assert r["group_admin"] and not r["group_owner"]
    r2 = roles_from_raw_and_group(sender_id="1", group=group, astrbot_admin=False)
    assert r2["group_owner"]


def test_astrbot_admin_only():
    r = roles_from_raw_and_group(
        sender_id="9",
        raw_message={"sender": {"role": "member"}},
        astrbot_admin=True,
    )
    assert r["astrbot_admin"]
    assert not r["group_owner"]


class _FakeEvent:
    def __init__(self, sender_id, raw=None, group=None, is_admin=False, fetched_group=None):
        self._sid = sender_id
        self._admin = is_admin
        self._fetched = fetched_group
        self.message_obj = SimpleNamespace(raw_message=raw, group=group)
        self.role = "admin" if is_admin else "member"

    def get_sender_id(self):
        return self._sid

    def is_admin(self):
        return self._admin

    async def get_group(self):
        return self._fetched


def test_resolve_and_manage_gates():
    async def _run():
        owner_ev = _FakeEvent("1", raw={"sender": {"role": "owner"}})
        assert await can_manage_group_feature(owner_ev)

        admin_ev = _FakeEvent("2", raw={"sender": {"role": "admin"}})
        assert await can_manage_group_feature(admin_ev)

        member_ev = _FakeEvent("3", raw={"sender": {"role": "member"}})
        assert not await can_manage_group_feature(member_ev)

        astrbot_ev = _FakeEvent("3", raw={"sender": {"role": "member"}}, is_admin=True)
        assert await can_manage_group_feature(astrbot_ev)

        # get_group fallback
        g = SimpleNamespace(group_owner="99", group_admins=[])
        fg_ev = _FakeEvent("99", raw={"sender": {"role": "member"}}, fetched_group=g)
        roles = await resolve_roles(fg_ev)
        assert roles["group_owner"]

        # mcq whitelist
        assert await can_use_mcq(member_ev, whitelist=["3"])
        assert not await can_use_mcq(member_ev, whitelist=[], min_group_level=0)

    asyncio.run(_run())
