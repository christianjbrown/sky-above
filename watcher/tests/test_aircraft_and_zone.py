from fakes import HOME, FakeHttp, plane
from flights_watcher.aircraft import Aircraft
from flights_watcher.geo import Location
from flights_watcher.rotorcraft import KnownRotorcraft
from flights_watcher.sources import Tar1090AircraftSource
from flights_watcher.zone import Zone


def test_distance_matches_a_known_pair():
    heathrow = Location(51.4706, -0.46194)
    assert round(HOME.distance_km(heathrow), 1) == 32.0


def test_parses_a_tar1090_record():
    aircraft = Aircraft.from_tar1090(
        {
            "hex": "4ca7b5",
            "flight": "RYR40AL ",
            "r": "EI-DLC",
            "t": "B738",
            "desc": "BOEING 737-800",
            "lat": 51.47,
            "lon": 0.01,
            "alt_baro": 15675,
            "gs": 431.2,
            "track": 92.5,
            "baro_rate": -1088,
        }
    )
    assert aircraft.callsign == "RYR40AL"
    assert aircraft.registration == "EI-DLC"
    assert aircraft.location == Location(51.47, 0.01)
    assert aircraft.altitude_ft == 15675
    assert not aircraft.on_ground
    assert aircraft.vertical_rate_fpm == -1088


def test_a_callsign_the_decoder_could_not_read_is_no_callsign():
    assert Aircraft.from_tar1090({"hex": "406b9c", "flight": "@@@@@@@@"}).callsign is None
    assert Aircraft.from_tar1090({"hex": "406b9c", "flight": "EZY353A "}).callsign == "EZY353A"


def test_a_record_without_position_or_details_still_parses():
    aircraft = Aircraft.from_tar1090({"hex": "406b9c", "alt_baro": "ground", "flight": "  "})
    assert aircraft.location is None
    assert aircraft.on_ground
    assert aircraft.altitude_ft is None
    assert aircraft.callsign is None


def test_source_reads_every_aircraft_from_the_feed():
    http = FakeHttp({"http://pie/data/aircraft.json": {"aircraft": [{"hex": "a"}, {"hex": "b"}, {"nohex": 1}]}})
    found = Tar1090AircraftSource("http://pie/data/aircraft.json", http).aircraft()
    assert [a.hex for a in found] == ["a", "b"]


class ListSource:
    def __init__(self, aircraft: list[Aircraft]) -> None:
        self._aircraft = aircraft

    def aircraft(self) -> list[Aircraft]:
        return self._aircraft


def test_a_helicopter_that_sends_no_category_is_known_by_its_type():
    source = ListSource(
        [
            plane("police", type_code="EC45", category=None),
            plane("airliner", type_code="A320", category=None),
            plane("glider", type_code="EC45", category="B1"),
            plane("unknown", type_code=None, category=None),
        ]
    )
    found = KnownRotorcraft(source, ["EC45"]).aircraft()
    assert [a.category for a in found] == ["A7", None, "B1", None]


def test_the_bundled_rotorcraft_types_include_common_helicopters():
    found = KnownRotorcraft.bundled(ListSource([plane(type_code=code) for code in ("EC45", "EC35", "A139", "A320")])).aircraft()
    assert [a.category for a in found] == ["A7", "A7", "A7", None]


def test_zone_keeps_nearby_airborne_planes_nearest_first():
    near = plane("near", lat=HOME.lat + 0.0003)
    middle = plane("middle", lat=HOME.lat + 0.015)
    far = plane("far", lat=HOME.lat + 0.15)
    landed = plane("landed", lat=HOME.lat, on_ground=True)
    nowhere = plane("nowhere", location=None)
    sightings = Zone(HOME, 3).sightings([far, middle, landed, near, nowhere])
    assert [s.aircraft.hex for s in sightings] == ["near", "middle"]
    assert sightings[0].distance_km < 0.1


def test_the_decoder_database_marks_military_planes_and_their_owner():
    raw = {"hex": "43c6f1", "flight": "RRR4321 ", "lat": 51.5, "lon": 0.0, "dbFlags": 1, "ownOp": "Royal Air Force"}
    raf = Aircraft.from_tar1090(raw)
    assert raf.military and raf.operator == "Royal Air Force"
    assert not Aircraft.from_tar1090({**raw, "dbFlags": 2}).military
    assert not Aircraft.from_tar1090({"hex": "abc123"}).military


def test_a_zone_says_how_far_out_it_reaches():
    assert Zone(HOME, 3).radius_km == 3
