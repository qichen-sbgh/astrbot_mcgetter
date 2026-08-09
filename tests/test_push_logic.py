from __future__ import annotations

import random

from script.mcmod.push_logic import (
    can_push_more,
    cold_room_probability,
    record_push,
    should_trigger_cold_room,
    PushGroupState,
)


def test_probability_formula_no_cap():
    assert cold_room_probability(20, 0) == 60.0
    assert cold_room_probability(5, 2) == -5.0
    # no 80 clamp: large idle yields large p
    assert cold_room_probability(100, 0) == 300.0


def test_should_trigger_skip_recent_and_nonpositive():
    rng = random.Random(0)
    assert not should_trigger_cold_room(5, 0, idle_skip_minutes=10, rng=rng)
    assert not should_trigger_cold_room(30, 10, idle_skip_minutes=10, rng=rng)  # p negative-ish
    # force always: p huge
    rng2 = random.Random(1)
    assert should_trigger_cold_room(50, 0, idle_skip_minutes=10, daily_cap=10, rng=rng2)


def test_evening_increments_count_and_daily_cap():
    from datetime import datetime

    now = datetime.now()
    st = PushGroupState(enabled=True, today_date=now.date().isoformat(), today_push_count=0)
    st = record_push(st, "evening", now_ts=now.timestamp())
    assert st.today_push_count == 1
    assert st.last_push_kind == "evening"
    st.today_push_count = 4
    assert not can_push_more(st, daily_cap=4, now=now)
