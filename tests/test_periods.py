from datetime import time

import pytest

from services.periods import Schedule
from tests.conftest import at

SCHEDULE = Schedule(time(6, 0), weekly_day=6, monthly_day=1)


def test_day_slot_is_today_after_the_time():
    assert SCHEDULE.last_slot("day", at(2026, 10, 30, 6, 0)) == at(2026, 10, 30)
    assert SCHEDULE.last_slot("day", at(2026, 10, 30, 23, 59)) == at(2026, 10, 30)


def test_day_slot_is_yesterday_before_the_time():
    assert SCHEDULE.last_slot("day", at(2026, 10, 30, 5, 59)) == at(2026, 10, 29)


def test_week_slot_is_the_last_sunday():
    # 30.10.2026 is a Friday, 25.10 and 01.11 are Sundays
    assert SCHEDULE.last_slot("week", at(2026, 10, 30, 12)) == at(2026, 10, 25)
    assert SCHEDULE.last_slot("week", at(2026, 11, 1, 6)) == at(2026, 11, 1)
    assert SCHEDULE.last_slot("week", at(2026, 11, 1, 5)) == at(2026, 10, 25)


def test_month_slot():
    assert SCHEDULE.last_slot("month", at(2026, 10, 30)) == at(2026, 10, 1)
    assert SCHEDULE.last_slot("month", at(2026, 11, 1, 5)) == at(2026, 10, 1)
    assert SCHEDULE.last_slot("month", at(2026, 1, 1, 5)) == at(2025, 12, 1)


def test_next_slots():
    now = at(2026, 10, 30, 12)
    assert SCHEDULE.next_slot("day", now) == at(2026, 10, 31)
    assert SCHEDULE.next_slot("week", now) == at(2026, 11, 1)
    assert SCHEDULE.next_slot("month", now) == at(2026, 11, 1)
    assert SCHEDULE.next_slot("month", at(2026, 12, 5)) == at(2027, 1, 1)


def test_slot_keeps_the_wall_clock_across_dst():
    # Poland leaves summer time on 25.10.2026 at 03:00
    slot = SCHEDULE.last_slot("day", at(2026, 10, 25, 7))
    assert (slot.hour, slot.minute) == (6, 0)
    assert slot.utcoffset().total_seconds() == 3600
    before = SCHEDULE.last_slot("day", at(2026, 10, 24, 7))
    assert before.utcoffset().total_seconds() == 7200


def test_unknown_period():
    with pytest.raises(ValueError):
        SCHEDULE.last_slot("year", at(2026, 10, 30))
