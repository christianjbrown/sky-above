import math

import pytest

from fakes import HOME
from fakes import plane as fake_plane
from flights_watcher.approach import ApproachFinder, ClosestApproach, LandsFirst, OverheadAndApproaching, SteeredIn
from flights_watcher.zone import Zone

KM_PER_DEGREE_LON = 111.32 * math.cos(math.radians(HOME.lat))


def east(km: float) -> float:
    return HOME.lon + km / KM_PER_DEGREE_LON


def north(km: float) -> float:
    return HOME.lat + km / 110.574


def plane(hex_code: str, **fields):
    """A plane in level flight, well clear of the rules for arrivals and departures,
    unless a test says otherwise."""
    return fake_plane(hex_code, **{"altitude_ft": 20000, "vertical_rate_fpm": 0, **fields})


def finder(steady_polls: int = 1, per_km: float = 0) -> ApproachFinder:
    return ApproachFinder(ClosestApproach(HOME, 60), HOME, 2.0, steady_polls, per_km, 3.0, 0.3, [LandsFirst(), SteeredIn(10000, 10, -300)])


def overhead_and_approaching() -> OverheadAndApproaching:
    return OverheadAndApproaching(Zone(HOME, 2.0), finder(), ClosestApproach(HOME, 60), 10)


def test_a_plane_flying_at_home_is_approaching_with_the_time_until_overhead():
    sightings = finder().sightings([plane("inbound", lat=HOME.lat, lon=east(20), track_deg=270.0, ground_speed_kt=240.0)])
    assert [s.aircraft.hex for s in sightings] == ["inbound"]
    # 20 km at 240 knots (444.48 km/h) is 162 seconds.
    assert sightings[0].overhead_in_seconds == pytest.approx(162, abs=1)
    assert sightings[0].distance_km == pytest.approx(20, abs=0.1)


def test_planes_flying_away_passing_wide_or_already_overhead_are_not_approaching():
    away = plane("away", lat=HOME.lat, lon=east(20), track_deg=90.0)
    wide = plane("wide", lat=north(5), lon=east(20), track_deg=270.0)
    overhead = plane("overhead", lat=HOME.lat, lon=east(1), track_deg=270.0)
    hovering = plane("hovering", lat=HOME.lat, lon=east(5), track_deg=270.0, ground_speed_kt=20.0)
    landed = plane("landed", lat=HOME.lat, lon=east(5), track_deg=270.0, on_ground=True)
    no_track = plane("no-track", lat=HOME.lat, lon=east(5), track_deg=None)
    assert finder().sightings([away, wide, overhead, hovering, landed, no_track]) == []


def test_a_plane_passing_just_inside_the_edge_counts():
    sightings = finder().sightings([plane("edge", lat=north(1.5), lon=east(5), track_deg=270.0)])
    assert [s.aircraft.hex for s in sightings] == ["edge"]


def test_a_plane_far_out_counts_once_its_line_passes_inside_the_zone():
    assert finder().sightings([plane("edge", lat=north(1.5), lon=east(30), track_deg=270.0)])
    assert not finder().sightings([plane("wide", lat=north(2.5), lon=east(30), track_deg=270.0)])


def test_a_plane_counts_only_once_its_line_has_held_steady_for_a_few_looks():
    approaches = finder(steady_polls=3)
    for look in range(2):
        assert not approaches.sightings([plane("steady", lat=HOME.lat, lon=east(10 - look), track_deg=270.0 + look)])
    assert approaches.sightings([plane("steady", lat=HOME.lat, lon=east(8), track_deg=271.5)])


def test_a_plane_further_out_has_to_hold_its_course_for_longer():
    # Two looks, plus one for each km (or part of one) beyond the 2 km zone.
    def looks_until_counted(km: float) -> int:
        approaches = finder(steady_polls=2, per_km=1)
        for look in range(1, 30):
            if approaches.sightings([plane("p", lat=HOME.lat, lon=east(km), track_deg=270.0)]):
                return look
        return 0

    assert looks_until_counted(4.5) == 5
    assert looks_until_counted(10.5) == 11


def test_a_turning_plane_that_points_at_home_for_a_moment_does_not_count():
    approaches = finder(steady_polls=3)
    # Turning at 3 degrees a second, the line through home only lines up briefly.
    for _look, track in enumerate([264.0, 267.0, 270.0, 273.0, 276.0]):
        assert not approaches.sightings([plane("turning", lat=HOME.lat, lon=east(10), track_deg=track)])


def test_a_plane_that_will_land_before_it_gets_here_does_not_count():
    # 9 km out at 120 knots is 146 seconds away; 1,400 ft at 700 ft a minute lands in 120.
    landing = plane("landing", lat=HOME.lat, lon=east(9), track_deg=270.0, ground_speed_kt=120.0, altitude_ft=1400, vertical_rate_fpm=-700)
    assert not finder().sightings([landing])
    gentle = plane("gentle", lat=HOME.lat, lon=east(9), track_deg=270.0, ground_speed_kt=120.0, altitude_ft=4000, vertical_rate_fpm=-700)
    assert [s.aircraft.hex for s in finder().sightings([gentle])] == ["gentle"]


def test_a_plane_climbing_out_after_take_off_counts_once_its_course_is_steady():
    # Off a nearby runway at 4,500 ft and still climbing, first heard 7 km out.
    departing = plane("departing", lat=HOME.lat, lon=east(7), track_deg=270.0, altitude_ft=4500, vertical_rate_fpm=1500)
    found = finder(steady_polls=5, per_km=2)
    for _ in range(14):
        assert not found.sightings([departing])
    assert [s.aircraft.hex for s in found.sightings([departing])] == ["departing"]


def test_an_arrival_coming_down_low_far_out_does_not_count_until_it_is_close():
    # Into a nearby airport, 27 km out at 8,575 ft: air traffic control steers it a heading at a time.
    far = plane("arriving", lat=HOME.lat, lon=east(27), track_deg=270.0, altitude_ft=8575, vertical_rate_fpm=-1000)
    assert not finder().sightings([far])
    near = plane("arriving", lat=HOME.lat, lon=east(8), track_deg=270.0, altitude_ft=8575, vertical_rate_fpm=-1000)
    assert finder().sightings([near])
    high = plane("high", lat=HOME.lat, lon=east(27), track_deg=270.0, altitude_ft=15000, vertical_rate_fpm=-1000)
    assert finder().sightings([high])


def test_a_plane_once_counted_is_followed_until_it_passes_its_closest_point():
    approaches = finder(steady_polls=1)
    assert approaches.sightings([plane("followed", lat=HOME.lat, lon=east(10), track_deg=270.0)])
    # A drift that takes its line just outside the zone does not drop it.
    assert approaches.sightings([plane("followed", lat=north(2.2), lon=east(9), track_deg=270.0)])
    # Once its closest point is behind it, it stops counting.
    assert not approaches.sightings([plane("followed", lat=HOME.lat, lon=east(8), track_deg=60.0)])
    assert not approaches.sightings([plane("followed", lat=HOME.lat, lon=east(7), track_deg=300.0)])


def test_a_plane_that_turns_away_from_the_zone_stops_counting():
    approaches = finder(steady_polls=1)
    assert approaches.sightings([plane("turning", lat=HOME.lat, lon=east(10), track_deg=270.0)])
    assert not approaches.sightings([plane("turning", lat=HOME.lat, lon=east(9), track_deg=300.0)])
    # It comes back once its line passes through the zone again.
    assert approaches.sightings([plane("turning", lat=HOME.lat, lon=east(8), track_deg=270.0)])


def test_the_soonest_comes_first_after_the_planes_already_overhead():
    sky = [
        plane("later", lat=HOME.lat, lon=east(30), track_deg=270.0),
        plane("overhead", lat=HOME.lat, lon=east(1), track_deg=90.0),
        plane("sooner", lat=HOME.lat, lon=east(10), track_deg=270.0),
    ]
    sightings = overhead_and_approaching().sightings(sky)
    assert [s.aircraft.hex for s in sightings] == ["overhead", "sooner", "later"]
    assert sightings[0].overhead_in_seconds is None


def test_a_plane_in_the_zone_still_closing_in_gets_its_time_to_the_closest_point():
    closing = plane("closing", lat=north(0.5), lon=east(1.9), track_deg=270.0, ground_speed_kt=240.0)
    nearly = plane("nearly", lat=north(-0.5), lon=east(0.5), track_deg=270.0, ground_speed_kt=240.0)
    by_hex = {s.aircraft.hex: s for s in overhead_and_approaching().sightings([closing, nearly])}
    # 1.9 km at 240 knots is about 15 seconds; 0.5 km is about 4, too soon to bother saying.
    assert by_hex["closing"].overhead_in_seconds == pytest.approx(15.4, abs=0.5)
    assert by_hex["nearly"].overhead_in_seconds is None


def test_a_plane_without_a_position_or_track_or_height_is_judged_on_what_it_has():
    no_position = plane("lost", location=None, track_deg=270.0)
    no_height = plane("no-height", lat=HOME.lat, lon=east(27), track_deg=270.0, altitude_ft=None, vertical_rate_fpm=None)
    assert [s.aircraft.hex for s in finder().sightings([no_position, no_height])] == ["no-height"]
