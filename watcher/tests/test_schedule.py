from datetime import datetime

import pytest

from flights_watcher.schedule import QuietHours

# 2026-11-06 is a Friday.
FRIDAY = datetime(2026, 11, 6)


def at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    return FRIDAY.replace(day=FRIDAY.day + day_offset, hour=hour, minute=minute)


def test_a_window_without_days_is_quiet_every_day_and_may_wrap_midnight():
    overnight = QuietHours.parse("23:00-07:00")
    assert overnight.is_quiet(at(0, 23))
    assert overnight.is_quiet(at(1, 3))
    assert not overnight.is_quiet(at(1, 7))
    assert not overnight.is_quiet(at(1, 12))
    daytime = QuietHours.parse("09:00-17:00")
    assert daytime.is_quiet(at(2, 12))
    assert not daytime.is_quiet(at(2, 20))


def test_nothing_is_ever_quiet_without_windows():
    assert not QuietHours.parse("").is_quiet(at(0, 3))
    assert not QuietHours.parse(" , ").is_quiet(at(0, 3))


def test_a_day_window_is_quiet_only_on_that_day_and_adds_to_the_daily_one():
    hours = QuietHours.parse("00:00-08:00, Sat 00:00-12:00")
    assert hours.is_quiet(at(0, 7, 59))
    assert not hours.is_quiet(at(0, 9))
    assert hours.is_quiet(at(1, 11, 59))
    assert not hours.is_quiet(at(1, 12))
    assert not hours.is_quiet(at(2, 9))


def test_an_overnight_day_window_runs_from_that_night_into_the_next_morning():
    friday_night = QuietHours.parse("Fri 22:00-06:00")
    assert friday_night.is_quiet(at(0, 23))
    assert friday_night.is_quiet(at(1, 5))
    assert not friday_night.is_quiet(at(1, 23))
    assert not friday_night.is_quiet(at(0, 5))


def test_a_run_of_days_may_wrap_the_week_and_names_may_be_spelt_out():
    weekend = QuietHours.parse("saturday-Mon 09:00-10:00")
    assert weekend.is_quiet(at(1, 9))
    assert weekend.is_quiet(at(2, 9))
    assert weekend.is_quiet(at(3, 9))
    assert not weekend.is_quiet(at(4, 9))
    assert not weekend.is_quiet(at(0, 9))
    assert QuietHours.parse("Mon-Fri 09:00-17:00").is_quiet(at(0, 12))


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("Sa 09:00-10:00", "'Sa' is not a day of the week"),
        ("Fridays 09:00-10:00", "'Fridays' is not a day of the week"),
        ("09:00", "should look like 23:00-07:00"),
        ("Fri 25:00-26:00", "hour must be in 0..23"),
    ],
)
def test_a_mistyped_window_says_what_is_wrong(spec, message):
    with pytest.raises(ValueError, match=message):
        QuietHours.parse(spec)
