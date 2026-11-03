import logging

import pytest

from fakes import HOME, FakeClock, plane
from flights_watcher.aircraft import Aircraft
from flights_watcher.emergency import (
    DeclaredEmergency,
    Distress,
    Emergency,
    EmergencyAlert,
    EmergencyLog,
    EmergencyMessages,
    FirstEmergencies,
    HeldEmergencies,
    SteepClimbOrDescent,
)
from flights_watcher.emergency_speech import EmergencyAnnouncer, EmergencyWording
from flights_watcher.geo import Location
from flights_watcher.naming import Service
from flights_watcher.priority import ServicesStay
from flights_watcher.speech import AnnouncementWording, InterruptedByEmergency, SpeechFailed, SpokenWhereabouts
from flights_watcher.zone import Sighting, Zone

LOG = logging.getLogger("test")
# A plane about 40 km north of home, far outside any zone.
FAR = HOME.lat + 0.36


def squawking(code: str | None = "7700", hex_code: str = "abc123", **overrides) -> Aircraft:
    return plane(hex_code, lat=FAR, squawk=code, **overrides)


def test_the_feed_gives_the_squawk_and_the_emergency_status_but_not_none():
    raw = {"hex": "abc123", "squawk": "7700", "emergency": "general"}
    assert Aircraft.from_tar1090(raw).squawk == "7700"
    assert Aircraft.from_tar1090(raw).emergency == "general"
    assert Aircraft.from_tar1090({**raw, "emergency": "none"}).emergency is None
    assert Aircraft.from_tar1090({"hex": "abc123"}).squawk is None


@pytest.mark.parametrize(
    ("squawk", "status", "expected"),
    [
        ("7700", None, Emergency("general", "7700")),
        ("7600", None, Emergency("nordo", "7600")),
        ("7500", None, Emergency("unlawful", "7500")),
        ("1234", "nordo", Emergency("nordo")),
        ("7700", "general", Emergency("general", "7700")),
        (None, "downed", Emergency("downed")),
        ("1234", "lifeguard", None),
        ("2000", "minfuel", None),
        (None, None, None),
    ],
)
def test_a_declared_emergency_is_read_from_the_squawk_or_the_status(squawk, status, expected):
    assert DeclaredEmergency().of(plane(squawk=squawk, emergency=status)) == expected


def test_the_kinds_have_labels_for_the_card():
    assert Emergency("unlawful", "7500").label == "Unlawful interference"
    assert Emergency("descent").label == "Rapid descent"


def test_a_steep_climb_or_descent_counts_for_airliners_only():
    steep = SteepClimbOrDescent(descent_fpm=6000, climb_fpm=8000)
    assert steep.of(plane(vertical_rate_fpm=-6400)) == Emergency("descent")
    assert steep.of(plane(vertical_rate_fpm=8000)) == Emergency("climb")
    assert steep.of(plane(vertical_rate_fpm=-3000)) is None
    assert steep.of(plane(vertical_rate_fpm=5000)) is None
    assert steep.of(plane(vertical_rate_fpm=None)) is None
    assert steep.of(plane(vertical_rate_fpm=-9000, on_ground=True)) is None
    assert steep.of(plane(vertical_rate_fpm=-9000, military=True)) is None
    assert steep.of(plane(vertical_rate_fpm=-9000, category="A7")) is None
    assert steep.of(plane(vertical_rate_fpm=12000, category="A6")) is None


def held(clock: FakeClock, polls: int = 3, clear: float = 60) -> HeldEmergencies:
    return HeldEmergencies(DeclaredEmergency(), HOME, polls, clear, clock)


def test_an_emergency_counts_once_it_has_held_for_a_few_looks():
    clock = FakeClock()
    emergencies = held(clock)
    assert emergencies.current([squawking()]) == []
    assert emergencies.current([squawking()]) == []
    [distress] = emergencies.current([squawking()])
    assert distress.emergency == Emergency("general", "7700")
    assert distress.sighting.distance_km == pytest.approx(40, abs=0.5)


def test_a_squawk_seen_for_a_single_look_starts_the_count_again():
    emergencies = held(FakeClock(), polls=2)
    emergencies.current([squawking()])
    emergencies.current([squawking("1234")])
    assert emergencies.current([squawking()]) == []
    assert emergencies.current([squawking()]) != []


def test_an_emergency_stays_through_a_flicker_and_ends_once_it_has_been_gone_a_while():
    clock = FakeClock()
    emergencies = held(clock, polls=1, clear=60)
    emergencies.current([squawking()])
    clock.seconds = 30
    assert emergencies.current([squawking("1234")]) != []
    clock.seconds = 59
    assert emergencies.current([]) != []
    clock.seconds = 60
    assert emergencies.current([]) == []


def test_a_plane_without_a_position_waits_for_one_then_keeps_its_last():
    emergencies = held(FakeClock(), polls=1)
    assert emergencies.current([squawking(location=None)]) == []
    emergencies.current([squawking()])
    [distress] = emergencies.current([squawking(location=None, altitude_ft=3000)])
    assert distress.sighting.aircraft.location == Location(FAR, HOME.lon)
    assert distress.sighting.aircraft.altitude_ft == 3000


def test_the_first_plane_to_have_an_emergency_stays_first():
    emergencies = held(FakeClock(), polls=1)
    emergencies.current([squawking(hex_code="first")])
    found = emergencies.current([squawking(hex_code="second"), squawking(hex_code="first")])
    assert [d.sighting.aircraft.hex for d in found] == ["first", "second"]


def test_a_declared_emergency_goes_before_one_guessed_from_the_flying():
    clock = FakeClock()
    falling = squawking("7600", vertical_rate_fpm=-7000)
    either = FirstEmergencies([held(clock, polls=1), HeldEmergencies(SteepClimbOrDescent(6000, 8000), HOME, 1, 60, clock)])
    [distress] = either.current([falling, squawking(None, hex_code="other")])
    assert distress.emergency.kind == "nordo"
    assert [d.emergency.kind for d in either.current([squawking(None, hex_code="falling", vertical_rate_fpm=-7000)])] == [
        "nordo",
        "descent",
    ]


def distress(kind: str = "general", squawk: str | None = "7700", hex_code: str = "abc123") -> Distress:
    return Distress(Sighting(squawking(squawk, hex_code=hex_code), 40.0), Emergency(kind, squawk))


def test_the_log_says_when_an_emergency_starts_changes_and_ends(caplog):
    log = EmergencyLog(LOG)
    with caplog.at_level(logging.INFO):
        log.note([distress()])
        log.note([distress()])
        log.note([distress("descent", None)])
        log.note([])
    assert [r.getMessage() for r in caplog.records] == [
        "BAW86S emergency: General emergency, squawking 7700, 40.0 km away at 4000 ft",
        "BAW86S emergency: Rapid descent, 40.0 km away at 4000 ft",
        "abc123 emergency is over",
    ]


def test_the_log_falls_back_to_the_hex_code():
    log = EmergencyLog(LOG)
    unnamed = Distress(Sighting(squawking(callsign=None), 40.0), Emergency("general", "7700"))
    log.note([unnamed])


class Cards:
    def build(self, sightings, aircraft):
        return {"type": "planes", "planes": [{"hex": s.aircraft.hex} for s in sightings], "speech": "planes voice"}


class Speech:
    def __init__(self) -> None:
        self.cards = []

    def speech_for(self, card):
        self.cards.append(card)
        return "speech/emergency.wav"


def test_the_message_marks_each_card_with_its_emergency_and_speaks_for_the_first():
    speech = Speech()
    message = EmergencyMessages(Cards(), speech).build([distress(), distress("climb", None, "other")], [])
    assert message["planes"] == [
        {"hex": "abc123", "emergency": {"kind": "general", "squawk": "7700", "label": "General emergency"}},
        {"hex": "other", "emergency": {"kind": "climb", "squawk": None, "label": "Rapid climb"}},
    ]
    assert message["speech"] == "speech/emergency.wav"
    assert speech.cards == [message["planes"][0]]


class Found:
    def __init__(self, distresses) -> None:
        self.distresses = distresses

    def current(self, aircraft):
        return self.distresses


class Notes:
    def __init__(self) -> None:
        self.noted = []

    def note(self, distresses):
        self.noted.append(distresses)


def test_the_alert_is_a_message_only_while_there_is_an_emergency():
    notes = Notes()
    assert EmergencyAlert(Found([]), EmergencyMessages(Cards(), Speech()), notes).message([]) is None
    alert = EmergencyAlert(Found([distress()]), EmergencyMessages(Cards(), Speech()), notes)
    assert alert.message([])["planes"][0]["hex"] == "abc123"
    assert len(notes.noted) == 2


class Nowhere:
    def phrase(self, card):
        return None


def wording(whereabouts=None) -> EmergencyWording:
    return EmergencyWording(AnnouncementWording((), Nowhere()), whereabouts or Nowhere())


ROUTED = {
    "hex": "abc123",
    "callsign": "BAW123",
    "flightNumber": "BA123",
    "origin": {"code": "ALC", "city": "Alicante"},
    "destination": {"code": "LGW", "city": "London"},
    "emergency": {"kind": "general", "squawk": "7700", "label": "General emergency"},
}


def test_an_emergency_is_announced_with_its_route_squawk_and_whereabouts():
    text = wording(SpokenWhereabouts(HOME)).text({**ROUTED, "lat": FAR, "lon": HOME.lon, "trackDeg": 180})
    assert text == (
        "Emergency. B A, 1 2 3, from Alicante, to London, squawking 7 7 0 0, general emergency, "
        "40 kilometres away, in a Northerly direction, heading South."
    )


def test_a_declared_emergency_without_a_squawk_says_what_the_crew_is_reporting():
    card = {**ROUTED, "emergency": {"kind": "downed", "squawk": None, "label": "Aircraft down"}}
    assert wording().text(card) == "Emergency. B A, 1 2 3, from Alicante, to London, reporting it is going down."


def test_a_plane_without_a_route_goes_by_its_callsign_and_type():
    card = {"hex": "abc123", "callsign": "BAW123", "aircraft": "Airbus A320", "emergency": ROUTED["emergency"]}
    assert wording().text(card) == "Emergency. B A W, 1 2 3, Airbus A320, squawking 7 7 0 0, general emergency."
    nameless = {"hex": "abc123", "emergency": ROUTED["emergency"]}
    assert wording().text(nameless) == "Emergency. An aircraft, squawking 7 7 0 0, general emergency."


def test_a_steep_climb_or_descent_is_announced_by_its_rate():
    descent = {**ROUTED, "verticalRateFpm": -7180, "emergency": {"kind": "descent", "squawk": None, "label": "Rapid descent"}}
    assert wording().text(descent) == "Rapid descent. B A, 1 2 3, from Alicante, to London, coming down at 7,200 feet a minute."
    climb = {**ROUTED, "emergency": {"kind": "climb", "squawk": None, "label": "Rapid climb"}}
    assert wording().text(climb).endswith("climbing at 0 feet a minute.")


class Clips:
    def __init__(self, failure: Exception | None = None) -> None:
        self.made: list[str] = []
        self.failure = failure

    def url_for(self, text):
        if self.failure:
            raise self.failure
        self.made.append(text)
        return f"speech/{len(self.made)}.wav"


def test_each_emergency_is_announced_once_and_again_only_when_it_changes_kind():
    clips = Clips()
    announcer = EmergencyAnnouncer(wording(), clips, 10, LOG)
    assert announcer.speech_for(ROUTED) == "speech/1.wav"
    assert announcer.speech_for(ROUTED) == "speech/1.wav"
    other = {**ROUTED, "hex": "def456"}
    assert announcer.speech_for(other) == "speech/2.wav"
    assert announcer.speech_for(ROUTED) is None
    worse = {**ROUTED, "emergency": {"kind": "nordo", "squawk": "7600", "label": "Radio failure"}}
    assert announcer.speech_for(worse) == "speech/3.wav"


@pytest.mark.parametrize("failure", [SpeechFailed("down"), OSError("disk full")])
def test_an_announcement_that_cannot_be_made_is_skipped(failure, caplog):
    announcer = EmergencyAnnouncer(wording(), Clips(failure), 10, LOG)
    assert announcer.speech_for(ROUTED) is None
    assert "could not make the announcement" in caplog.text


class Voice:
    def __init__(self) -> None:
        self.ends = 0

    def ended(self) -> None:
        self.ends += 1


def test_the_planes_voice_is_told_when_an_emergency_takes_the_card():
    voice = Voice()
    interrupted = InterruptedByEmergency(voice)
    assert interrupted.show({"type": "planes", "planes": [{"hex": "a"}]}) is False
    interrupted.show({"type": "followed"})
    interrupted.clear()
    assert voice.ends == 0
    interrupted.show({"type": "planes", "planes": [{"hex": "a", "emergency": {"kind": "general"}}]})
    assert voice.ends == 1


class ByCallsign:
    def of(self, aircraft):
        kinds = {"HLE": Service("Air ambulance", "ambulance"), "RRR": Service("Royal Air Force", "military")}
        return kinds.get((aircraft.callsign or "")[:3])


def stay() -> ServicesStay:
    return ServicesStay(Zone(HOME, 2), ByCallsign(), ("ambulance", "police"), HOME, 5)


def at_km(hex_code: str, km: float, **overrides) -> Aircraft:
    return plane(hex_code, lat=HOME.lat + km / 111.2, **overrides)


def test_an_air_ambulance_keeps_the_card_from_nearer_planes_until_it_is_5_km_out():
    finder = stay()
    ambulance = at_km("hle", 1.5, callsign="HLE27")
    assert [s.aircraft.hex for s in finder.sightings([ambulance])] == ["hle"]
    found = finder.sightings([at_km("hle", 3, callsign="HLE27"), at_km("jet", 0.5)])
    assert [s.aircraft.hex for s in found] == ["hle", "jet"]
    assert found[0].distance_km == pytest.approx(3, abs=0.05)
    assert [s.aircraft.hex for s in finder.sightings([at_km("hle", 1, callsign="HLE27"), at_km("jet", 0.5)])] == [
        "hle",
        "jet",
    ]
    assert [s.aircraft.hex for s in finder.sightings([at_km("hle", 5.5, callsign="HLE27"), at_km("jet", 0.5)])] == ["jet"]
    assert finder.sightings([at_km("hle", 3, callsign="HLE27")]) == []


def test_a_service_only_on_its_way_or_of_another_kind_is_not_held():
    on_its_way = Sighting(at_km("hle", 4, callsign="HLE27"), 4, approaching=True)

    class Approaching:
        def sightings(self, aircraft):
            return [on_its_way]

    finder = ServicesStay(Approaching(), ByCallsign(), ("ambulance",), HOME, 5)
    assert finder.sightings([on_its_way.aircraft]) == [on_its_way]
    military = stay()
    military.sightings([at_km("raf", 1, callsign="RRR4321")])
    assert military.sightings([at_km("raf", 3, callsign="RRR4321")]) == []


@pytest.mark.parametrize(
    "gone", [[], [at_km("hle", 1, callsign="HLE27", on_ground=True)], [at_km("hle", 1, callsign="HLE27", location=None)]]
)
def test_a_held_service_lets_go_once_it_lands_or_is_lost(gone):
    finder = stay()
    finder.sightings([at_km("hle", 1, callsign="HLE27")])
    finder.sightings(gone)
    assert finder.sightings([at_km("hle", 3, callsign="HLE27")]) == []
