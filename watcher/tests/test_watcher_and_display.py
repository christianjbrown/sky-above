import logging
import threading
from datetime import datetime, time

import pytest

from fakes import HOME, FakeClock, FakeDevice, RecordingDisplay, plane
from flights_watcher.display import CastDisplay, CoolingOff, CoolingOffDevice, LoggingDisplay
from flights_watcher.presence import Linger, MinimumShowing
from flights_watcher.rare import RareKinds
from flights_watcher.runner import Runner
from flights_watcher.schedule import QuietHours
from flights_watcher.watcher import ArrivalLog, Watcher
from flights_watcher.zone import Sighting, Zone

APP = "ABCD1234"
LOG = logging.getLogger("test")


class SkySource:
    def __init__(self) -> None:
        self.planes = []

    def aircraft(self):
        return list(self.planes)


class CountingMessages:
    def build(self, sightings, aircraft):
        return {"type": "planes", "planes": [{"hex": s.aircraft.hex} for s in sightings]}


class Standby:
    """Shows a followed flight while message is set."""

    def __init__(self) -> None:
        self.waiting = None

    def message(self, aircraft):
        return self.waiting


def make_watcher(
    quiet: str = "",
    clock: FakeClock | None = None,
    minimum: float = 0,
    standby: Standby | None = None,
    rare: tuple[str, ...] = ("helicopters", "military"),
    zone=None,
):
    clock = clock or FakeClock()
    sky, display = SkySource(), RecordingDisplay()
    watcher = Watcher(
        source=sky,
        zone=zone or Zone(HOME, 3),
        messages=CountingMessages(),
        display=display,
        quiet_hours=QuietHours.parse(quiet),
        linger=MinimumShowing(Linger(45, clock), minimum, clock),
        arrivals=ArrivalLog(LOG),
        clock=clock,
        standby=standby or Standby(),
        rare=RareKinds(rare),
        due_seconds=45,
        surroundings=Zone(HOME, 50),
    )
    return watcher, sky, display, clock


def test_shows_a_plane_overhead_and_hands_back_after_the_linger():
    watcher, sky, display, clock = make_watcher()
    sky.planes = [plane("overhead", lat=HOME.lat + 0.001)]
    watcher.tick()
    assert display.shown[-1]["planes"] == [{"hex": "overhead"}]
    sky.planes = []
    clock.seconds = 30
    watcher.tick()
    assert display.clears == 0
    clock.seconds = 45
    watcher.tick()
    assert display.clears == 1
    clock.seconds = 200
    watcher.tick()
    assert display.clears == 1


def test_a_card_stays_up_for_its_minimum_even_after_the_plane_leaves():
    watcher, sky, display, clock = make_watcher(minimum=120)
    sky.planes = [plane("quick", lat=HOME.lat + 0.001)]
    watcher.tick()
    sky.planes = []
    clock.seconds = 60
    watcher.tick()
    assert display.clears == 0
    clock.seconds = 119
    watcher.tick()
    assert display.clears == 0
    clock.seconds = 120
    watcher.tick()
    assert display.clears == 1


def test_the_card_keeps_following_the_plane_after_it_leaves_until_its_time_is_up():
    watcher, sky, display, clock = make_watcher(minimum=60)
    sky.planes = [plane("leaving", lat=HOME.lat + 0.001)]
    watcher.tick()
    for second, lat in ((10, 0.04), (20, 0.06)):
        clock.seconds = second
        sky.planes = [plane("leaving", lat=HOME.lat + lat)]
        watcher.tick()
    assert len(display.shown) == 3 and display.shown[-1]["planes"] == [{"hex": "leaving"}]
    clock.seconds = 60
    watcher.tick()
    assert display.clears == 1


def test_a_plane_that_takes_over_gets_its_own_minimum():
    watcher, sky, display, clock = make_watcher(minimum=120)
    sky.planes = [plane("first", lat=HOME.lat + 0.01)]
    watcher.tick()
    clock.seconds = 100
    sky.planes = [plane("first", lat=HOME.lat + 0.01), plane("closer", lat=HOME.lat + 0.001)]
    watcher.tick()
    assert display.shown[-1]["planes"][0] == {"hex": "closer"}
    sky.planes = []
    clock.seconds = 219
    watcher.tick()
    assert display.clears == 0
    clock.seconds = 220
    watcher.tick()
    assert display.clears == 1


def test_when_the_plane_leaves_another_in_the_zone_takes_the_card_without_a_clear():
    watcher, sky, display, clock = make_watcher()
    sky.planes = [plane("leaving", lat=HOME.lat + 0.001), plane("further", lat=HOME.lat + 0.02)]
    watcher.tick()
    sky.planes = [plane("further", lat=HOME.lat + 0.02)]
    clock.seconds = 100
    watcher.tick()
    assert display.shown[-1]["planes"] == [{"hex": "further"}]
    assert display.clears == 0


class InZoneOrOnItsWay:
    """The zone, plus any plane whose hex starts "coming" as one on its way, four minutes
    out, or half a minute for one whose hex says "soon"."""

    def sightings(self, aircraft):
        planes = list(aircraft)
        inside = Zone(HOME, 3).sightings([p for p in planes if not p.hex.startswith("coming")])
        coming = [Sighting(p, 20.0, 30.0 if "soon" in p.hex else 240.0, approaching=True) for p in planes if p.hex.startswith("coming")]
        return inside + coming


def test_a_plane_on_its_way_waits_for_the_card_on_screen_to_finish():
    watcher, sky, display, clock = make_watcher(minimum=60, zone=InZoneOrOnItsWay())
    sky.planes = [plane("first", lat=HOME.lat + 0.001)]
    watcher.tick()
    sky.planes = [plane("coming")]
    clock.seconds = 30
    watcher.tick()
    assert display.shown[-1]["planes"] == [{"hex": "first"}]
    clock.seconds = 59
    watcher.tick()
    assert display.shown[-1]["planes"] == [{"hex": "first"}]
    clock.seconds = 60
    watcher.tick()
    assert display.shown[-1]["planes"] == [{"hex": "coming"}]
    assert display.clears == 0


def test_a_plane_on_its_way_that_is_nearly_due_does_not_wait():
    watcher, sky, display, clock = make_watcher(minimum=60, zone=InZoneOrOnItsWay())
    sky.planes = [plane("first", lat=HOME.lat + 0.001)]
    watcher.tick()
    sky.planes = [plane("comingsoon")]
    clock.seconds = 10
    watcher.tick()
    assert display.shown[-1]["planes"] == [{"hex": "comingsoon"}]


def test_a_plane_coming_into_the_zone_takes_over_from_one_on_its_way_at_once():
    watcher, sky, display, clock = make_watcher(minimum=60, zone=InZoneOrOnItsWay())
    sky.planes = [plane("coming")]
    watcher.tick()
    clock.seconds = 5
    sky.planes = [plane("coming"), plane("close", lat=HOME.lat + 0.001)]
    watcher.tick()
    assert display.shown[-1]["planes"][0] == {"hex": "close"}


def test_a_plane_on_its_way_shows_at_once_over_a_followed_flight():
    standby = Standby()
    standby.waiting = {"type": "followed", "flight": {"ident": "BA4321"}}
    watcher, sky, display, _clock = make_watcher(minimum=60, zone=InZoneOrOnItsWay(), standby=standby)
    watcher.tick()
    sky.planes = [plane("coming")]
    watcher.tick()
    assert display.shown[-1]["planes"] == [{"hex": "coming"}]


def test_a_plane_arriving_during_the_linger_keeps_the_screen_on():
    watcher, sky, display, clock = make_watcher()
    sky.planes = [plane("first", lat=HOME.lat + 0.001)]
    watcher.tick()
    sky.planes = []
    clock.seconds = 30
    watcher.tick()
    sky.planes = [plane("next", lat=HOME.lat + 0.01)]
    clock.seconds = 40
    watcher.tick()
    clock.seconds = 80
    watcher.tick()
    assert display.shown[-1]["planes"] == [{"hex": "next"}]
    assert display.clears == 0


def test_a_followed_flight_shows_while_the_sky_is_clear():
    standby = Standby()
    watcher, _sky, display, _clock = make_watcher(standby=standby)
    watcher.tick()
    assert display.shown == []
    standby.waiting = {"type": "followed", "flight": {"ident": "BA4321"}}
    watcher.tick()
    assert display.shown[-1]["type"] == "followed"
    standby.waiting = None
    watcher.tick()
    assert display.clears == 1


def test_a_plane_overhead_interrupts_the_followed_flight_which_comes_back_after_it():
    standby = Standby()
    standby.waiting = {"type": "followed", "flight": {"ident": "BA4321"}}
    watcher, sky, display, clock = make_watcher(standby=standby)
    watcher.tick()
    sky.planes = [plane("overhead", lat=HOME.lat + 0.001)]
    watcher.tick()
    assert display.shown[-1]["type"] == "planes"
    sky.planes = []
    clock.seconds = 30
    watcher.tick()
    assert display.shown[-1]["type"] == "planes"
    clock.seconds = 45
    watcher.tick()
    assert display.shown[-1]["type"] == "followed"
    assert display.clears == 0


def test_quiet_hours_keep_the_followed_flight_off_the_screen():
    standby = Standby()
    standby.waiting = {"type": "followed", "flight": {"ident": "BA4321"}}
    night = FakeClock(datetime(2026, 11, 1, 23, 30))
    watcher, _sky, display, _ = make_watcher(quiet="23:00-07:00", clock=night, standby=standby)
    watcher.tick()
    assert display.shown == []


def test_ignores_planes_outside_the_zone():
    watcher, sky, display, _ = make_watcher()
    sky.planes = [plane("far", lat=HOME.lat + 0.15)]
    watcher.tick()
    assert display.shown == []
    assert display.clears == 0


def test_quiet_hours_keep_the_screen_dark():
    night = FakeClock(datetime(2026, 11, 1, 23, 30))
    watcher, sky, display, _ = make_watcher(quiet="23:00-07:00", clock=night)
    sky.planes = [plane("overhead", lat=HOME.lat + 0.001)]
    watcher.tick()
    assert display.shown == []


def test_helicopters_and_military_planes_still_get_a_card_in_quiet_hours_unless_told_not_to():
    night = FakeClock(datetime(2026, 11, 1, 23, 30))
    watcher, sky, display, _ = make_watcher(quiet="23:00-07:00", clock=night)
    sky.planes = [
        plane("airliner", lat=HOME.lat + 0.001),
        plane("helicopter", lat=HOME.lat + 0.002, category="A7"),
        plane("military", lat=HOME.lat + 0.003, military=True),
    ]
    watcher.tick()
    assert {p["hex"] for p in display.shown[-1]["planes"]} == {"helicopter", "military"}
    strict, sky, display, _ = make_watcher(quiet="23:00-07:00", clock=night, rare=())
    sky.planes = [plane("helicopter", lat=HOME.lat + 0.002, category="A7")]
    strict.tick()
    assert display.shown == []


def test_quiet_hours_parse_and_wrap_midnight():
    overnight = QuietHours.parse("23:00-07:00")
    assert overnight.is_quiet(time(23, 0))
    assert overnight.is_quiet(time(3, 0))
    assert not overnight.is_quiet(time(7, 0))
    assert not overnight.is_quiet(time(12, 0))
    daytime = QuietHours.parse("09:00-17:00")
    assert daytime.is_quiet(time(12, 0))
    assert not daytime.is_quiet(time(20, 0))
    assert not QuietHours.parse("").is_quiet(time(3, 0))


def test_cast_display_launches_only_on_an_idle_hub():
    device = FakeDevice(running="E8C28D3C", idle=True)
    display = CastDisplay(device, APP, LOG)
    assert display.show({"planes": []})
    assert device.launched == [APP]
    assert display.show({"planes": [1]})
    assert device.launched == [APP]
    assert len(device.sent) == 2


def test_cast_display_launches_again_once_the_hub_covers_the_card():
    device = FakeDevice(running=APP, idle=False)
    display = CastDisplay(device, APP, LOG)
    assert display.show({"planes": [1]})
    assert device.launched == []
    device.hidden = True
    assert display.show({"planes": [1]})
    assert (device.quits, device.launched) == (1, [APP])
    assert display.show({"planes": [1]})
    assert device.launched == [APP]
    assert len(device.sent) == 3


def test_cast_display_leaves_a_busy_hub_alone():
    device = FakeDevice(running="CC32E753", idle=False)
    display = CastDisplay(device, APP, LOG)
    assert not display.show({"planes": []})
    assert device.launched == []
    assert device.sent == []


def test_cast_display_only_quits_its_own_app():
    device = FakeDevice(running="CC32E753", idle=False)
    CastDisplay(device, APP, LOG).clear()
    assert device.quits == 0
    ours = FakeDevice(running=APP, idle=False)
    CastDisplay(ours, APP, LOG).clear()
    assert ours.quits == 1


def test_logging_display_logs_only_changes(caplog):
    display = LoggingDisplay(LOG)
    with caplog.at_level(logging.INFO, logger="test"):
        assert display.show({"planes": [{"hex": "a", "distanceKm": 1.0}]})
        display.show({"planes": [{"hex": "a", "distanceKm": 0.8}]})
        display.clear()
        display.clear()
    assert [r.getMessage().split(" ")[0:2] for r in caplog.records] == [["would", "show"], ["would", "hand"]]


def test_runner_survives_a_failing_tick_and_clears_on_stop():
    stop = threading.Event()

    class Flaky:
        calls = 0

        def tick(self):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise ConnectionError("feed down")
            stop.set()

    display = RecordingDisplay()
    Runner(Flaky(), display, 0, LOG).run(stop)
    assert Flaky.calls == 2
    assert display.clears == 1


def test_runner_reports_the_same_failure_only_once_and_survives_a_hub_that_will_not_clear(caplog):
    stop = threading.Event()

    class Failing:
        calls = 0

        def tick(self):
            Failing.calls += 1
            if Failing.calls == 3:
                stop.set()
            raise ConnectionError("feed down")

    class StuckDisplay(RecordingDisplay):
        def clear(self):
            raise TimeoutError("no answer")

    Runner(Failing(), StuckDisplay(), 0, LOG).run(stop)
    messages = [r.getMessage() for r in caplog.records]
    assert Failing.calls == 3
    assert messages.count("tick failed: ConnectionError: feed down") == 1
    assert any("could not hand the Hub back on shutdown: no answer" in m for m in messages)


def test_cast_display_mentions_a_busy_hub_once_until_it_gets_a_turn(caplog):
    device = FakeDevice(running="CC32E753", idle=False)
    display = CastDisplay(device, APP, LOG)
    with caplog.at_level(logging.INFO, logger="test"):
        assert not display.show({"planes": []})
        assert not display.show({"planes": []})
    assert [r.getMessage() for r in caplog.records] == ["Hub is busy with CC32E753, not casting"]


def test_logging_display_names_a_followed_flight_when_it_changes(caplog):
    display = LoggingDisplay(LOG)
    with caplog.at_level(logging.INFO, logger="test"):
        assert display.show({"type": "followed", "flight": {"ident": "BAW86S", "phase": "cruising"}})
        assert display.show({"type": "followed", "flight": {"ident": "BAW86S", "phase": "descending"}})
    assert [r.getMessage() for r in caplog.records] == ["would show followed flight BAW86S, cruising"]


def test_a_cooling_off_device_passes_everything_through_while_the_hub_answers():
    inner = FakeDevice()
    device = CoolingOffDevice(inner, FakeClock(), 30, LOG)
    assert device.is_idle() and not device.is_hidden()
    device.launch(APP)
    device.send({"type": "card"})
    device.quit()
    assert inner.launched == [APP]
    assert inner.sent == [{"type": "card"}]
    assert inner.quits == 1


class FlakyDevice(FakeDevice):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.failing = True

    def running_app_id(self):
        self.calls += 1
        if self.failing:
            raise ConnectionError("Hub unreachable")
        return super().running_app_id()


def test_a_failing_hub_is_left_alone_for_a_while():
    clock, flaky = FakeClock(), FlakyDevice()
    device = CoolingOffDevice(flaky, clock, 30, LOG)
    with pytest.raises(ConnectionError):
        device.running_app_id()
    with pytest.raises(CoolingOff):
        device.running_app_id()
    assert flaky.calls == 1
    flaky.failing = False
    clock.seconds += 31
    assert device.running_app_id() == "E8C28D3C"
    assert device.running_app_id() == "E8C28D3C"
    assert flaky.calls == 3
