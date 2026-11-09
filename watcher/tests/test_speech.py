import io
import json
import logging
import socket
import threading
import wave
from datetime import datetime

import pytest

from fakes import HOME, FakeClock
from flights_watcher.files import KeptFiles
from flights_watcher.heard import SpeechTiming, ahead
from flights_watcher.rare import RareKinds
from flights_watcher.schedule import QuietHours
from flights_watcher.speech import (
    AirbusNumbersSaid,
    AnnouncementWording,
    Announcer,
    BoeingNumbersSaid,
    EndOfShowing,
    QuietVoice,
    SaidAsWords,
    Silence,
    SpeechClips,
    SpeechFailed,
    SpokenArrival,
    SpokenWhereabouts,
    WyomingSpeech,
    spelled_flight,
)

INSTANT = SpeechTiming(13, 0, 0, 0)


class Announced:
    def __init__(self) -> None:
        self.flights: set[str] = set()

    def has(self, flight: str) -> bool:
        return flight in self.flights

    def add(self, flight: str) -> None:
        self.flights.add(flight)


LOG = logging.getLogger("test")


class Nowhere:
    def phrase(self, card):
        return None


NOWHERE = Nowhere()
LONDON = ("LHR", "STN", "CDG", "ORY")
CARD = {
    "hex": "4ca7b5",
    "callsign": "RYR20SW",
    "flightNumber": "FR20SW",
    "airline": "Ryanair",
    "helicopter": False,
    "origin": {"code": "ALC", "name": "Alicante-Elche Airport", "city": "Alicante"},
    "destination": {"code": "STN", "name": "London Stansted Airport", "city": "London"},
}


def test_wording_reads_the_flight_and_names_london_airports_in_full():
    assert AnnouncementWording(LONDON, NOWHERE).text(CARD) == "F R, 2 0 S W, from Alicante, to London Stansted."


@pytest.mark.parametrize(
    ("flight", "spoken"),
    [("BA1340", "B A, 1 3 4 0"), ("U21234", "U 2, 1 2 3 4"), ("BAW86S", "B A W, 8 6 S"), ("GEUYM", "G E U Y M")],
)
def test_the_airline_is_kept_apart_from_the_number_so_the_voice_does_not_run_them_together(flight, spoken):
    assert spelled_flight(flight) == spoken


def test_any_city_with_several_airports_names_them_in_full_and_drops_the_international():
    orly = {**CARD, "destination": {"code": "ORY", "name": "Orly Intl", "city": "Paris"}}
    assert AnnouncementWording(LONDON, NOWHERE).text(orly) == "F R, 2 0 S W, from Alicante, to Paris Orly."
    elsewhere = {**CARD, "destination": {"code": "BER", "name": "Berlin Brandenburg Airport", "city": "Berlin"}}
    assert AnnouncementWording(LONDON, NOWHERE).text(elsewhere) == "F R, 2 0 S W, from Alicante, to Berlin."


def test_an_air_ambulance_or_the_police_go_by_what_they_are():
    wording = AnnouncementWording(LONDON, NOWHERE)
    ambulance = {"callsign": "HLE27", "airline": "Air ambulance", "service": "ambulance", "helicopter": True}
    assert wording.text(ambulance) == "Air ambulance helicopter."
    assert wording.text({**ambulance, "airline": "Police", "service": "police", "helicopter": False}) == "Police."


def test_wording_names_london_airports_in_full_whoever_supplied_the_name():
    flightaware = {**CARD, "destination": {"code": "STN", "name": "Stansted", "city": "London"}}
    assert AnnouncementWording(LONDON, NOWHERE).text(flightaware) == "F R, 2 0 S W, from Alicante, to London Stansted."


def test_wording_says_how_far_away_and_which_way_to_look():
    north_north_east = {**CARD, "lat": HOME.lat + 0.0092, "lon": HOME.lon + 0.006}
    assert AnnouncementWording(LONDON, SpokenWhereabouts(HOME)).text(north_north_east) == (
        "F R, 2 0 S W, from Alicante, to London Stansted, 1.1 kilometres away, in a North-North-Easterly direction."
    )


def test_a_plane_on_its_way_says_when_it_will_be_overhead():
    arrival = SpokenArrival(HOME, 0.5)
    assert arrival.phrase({"overheadInSeconds": 230}) == "It will be overhead in about 4 minutes."
    assert arrival.phrase({"overheadInSeconds": 70}) == "It will be overhead in about a minute."
    assert arrival.phrase({"overheadInSeconds": 34}) == "It will be overhead in about 30 seconds."
    assert arrival.phrase({"overheadInSeconds": 8}) == "It will be overhead in a few seconds."
    assert arrival.phrase({"overheadInSeconds": None}) is None


def test_a_plane_within_half_a_kilometre_is_overhead_now():
    arrival = SpokenArrival(HOME, 0.5)
    assert arrival.phrase({"lat": HOME.lat + 0.004, "lon": HOME.lon, "overheadInSeconds": 3}) == "It's overhead now."
    assert arrival.phrase({"lat": HOME.lat + 0.006, "lon": HOME.lon, "overheadInSeconds": 5}) == ("It will be overhead in a few seconds.")
    assert arrival.phrase({"lat": HOME.lat + 0.006, "lon": HOME.lon, "overheadInSeconds": None}) is None


def test_whereabouts_round_for_speaking():
    whereabouts = SpokenWhereabouts(HOME)
    assert whereabouts.phrase({"lat": HOME.lat, "lon": HOME.lon + 0.0116}) == "800 metres away, in an Easterly direction"
    assert whereabouts.phrase({"lat": HOME.lat - 0.009, "lon": HOME.lon}) == "1 kilometre away, in a Southerly direction"
    assert whereabouts.phrase({"lat": None, "lon": None}) is None


def test_whereabouts_say_which_way_the_plane_is_heading():
    whereabouts = SpokenWhereabouts(HOME)
    south = {"lat": HOME.lat - 0.009, "lon": HOME.lon}
    assert whereabouts.phrase({**south, "trackDeg": 270.0}) == "1 kilometre away, in a Southerly direction, heading West"
    assert whereabouts.phrase({**south, "trackDeg": 30.0}) == ("1 kilometre away, in a Southerly direction, heading North-North-East")
    assert whereabouts.phrase({**south, "trackDeg": 355.0}).endswith("heading North")


def test_a_flight_with_no_route_goes_by_its_callsign_and_what_it_is():
    wording = AnnouncementWording(LONDON, NOWHERE)
    charter = {"hex": "a", "callsign": "SXN39", "aircraft": "Agusta AW-139", "helicopter": True}
    assert wording.text(charter) == "S X N, 3 9, Agusta AW-139 helicopter."
    assert wording.text({**charter, "aircraft": None}) == "S X N, 3 9, helicopter."
    assert wording.text({**charter, "aircraft": "Robinson R44 Helicopter"}) == "S X N, 3 9, Robinson R44 Helicopter."
    assert wording.text({**CARD, "destination": None, "aircraft": "Boeing 737-800"}) == "F R, 2 0 S W, Boeing 737-800."
    assert wording.text({"hex": "c", "callsign": "GEUYM"}) == "G E U Y M."


def test_a_plane_waits_for_its_callsign_before_it_is_announced():
    wording = AnnouncementWording(LONDON, NOWHERE)
    assert wording.text({"hex": "a", "callsign": None, "aircraft": "Agusta AW-139", "helicopter": True}) is None


class CountingSynth:
    def __init__(self, fail: bool = False) -> None:
        self.texts: list[str] = []
        self.fail = fail

    def synthesize(self, text: str) -> bytes:
        self.texts.append(text)
        if self.fail:
            raise SpeechFailed("server down")
        return b"RIFF" + text.encode()


def test_clips_are_made_once_per_sentence(tmp_path):
    synth = CountingSynth()
    clips = SpeechClips(KeptFiles(tmp_path, "speech/", 2, ".wav"), synth)
    first = clips.url_for("one")
    assert first.startswith("speech/") and first.endswith(".wav")
    assert clips.url_for("one") == first
    assert synth.texts == ["one"]


def test_announcer_speaks_once_per_plane_and_survives_a_failure(tmp_path):
    synth = CountingSynth()
    announcer = Announcer(
        AnnouncementWording(LONDON, NOWHERE),
        NOWHERE,
        INSTANT,
        SpeechClips(KeptFiles(tmp_path, "speech/", 5, ".wav"), synth),
        Announced(),
        LOG,
    )
    url = announcer.speech_for(CARD)
    assert url and announcer.speech_for(CARD) == url
    assert len(synth.texts) == 1
    broken = Announcer(
        AnnouncementWording(LONDON, NOWHERE),
        NOWHERE,
        INSTANT,
        SpeechClips(KeptFiles(tmp_path / "x", "speech/", 5, ".wav"), CountingSynth(fail=True)),
        Announced(),
        LOG,
    )
    assert broken.speech_for(CARD) is None
    assert Silence().speech_for(CARD) is None


def test_a_closer_plane_is_announced_but_one_coming_back_is_not(tmp_path):
    announcer = Announcer(
        AnnouncementWording(LONDON, NOWHERE),
        NOWHERE,
        INSTANT,
        SpeechClips(KeptFiles(tmp_path, "speech/", 5, ".wav"), CountingSynth()),
        Announced(),
        LOG,
    )
    first = announcer.speech_for(CARD)
    closer = announcer.speech_for({**CARD, "hex": "closer", "flightNumber": "U28041"})
    assert closer and closer != first
    assert announcer.speech_for(CARD) is None


def test_a_plane_back_on_a_fresh_card_is_not_announced_again(tmp_path):
    announcer = Announcer(
        AnnouncementWording(LONDON, NOWHERE),
        NOWHERE,
        INSTANT,
        SpeechClips(KeptFiles(tmp_path, "speech/", 5, ".wav"), CountingSynth()),
        Announced(),
        LOG,
    )
    assert announcer.speech_for(CARD)
    EndOfShowing(QuietVoice(announcer, QuietHours.parse(""), FakeClock(), RareKinds(()))).clear()
    assert announcer.speech_for(CARD) is None
    assert EndOfShowing(Silence()).show({}) is False


def test_the_same_airframe_as_another_flight_is_announced_again(tmp_path):
    announcer = Announcer(
        AnnouncementWording(LONDON, NOWHERE),
        NOWHERE,
        INSTANT,
        SpeechClips(KeptFiles(tmp_path, "speech/", 5, ".wav"), CountingSynth()),
        Announced(),
        LOG,
    )
    announcer.speech_for(CARD)
    announcer.ended()
    assert announcer.speech_for({**CARD, "callsign": "RYR1234", "flightNumber": "FR1234"})


class EverySpeech:
    def speech_for(self, card):
        return "speech/" + card["hex"] + ".wav"


def test_the_voice_is_quiet_overnight_except_for_the_rare_kinds():
    rare = RareKinds(("helicopters", "military"))
    morning = QuietVoice(EverySpeech(), QuietHours.parse("00:00-10:00"), FakeClock(datetime(2026, 11, 2, 9, 59)), rare)
    assert morning.speech_for(CARD) is None
    assert morning.speech_for({**CARD, "hex": "police", "helicopter": True}) == "speech/police.wav"
    assert morning.speech_for({**CARD, "hex": "raf", "military": True}) == "speech/raf.wav"
    strict = QuietVoice(EverySpeech(), QuietHours.parse("00:00-10:00"), FakeClock(datetime(2026, 11, 2, 9, 59)), RareKinds(()))
    assert strict.speech_for({**CARD, "hex": "police", "helicopter": True}) is None
    later = QuietVoice(EverySpeech(), QuietHours.parse("00:00-10:00"), FakeClock(datetime(2026, 11, 2, 10, 0)), rare)
    assert later.speech_for(CARD) == "speech/4ca7b5.wav"


def test_a_military_plane_is_announced_by_who_flies_it_and_what_it_is():
    raf = {"callsign": "RRR4321", "airline": "Royal Air Force", "service": "military", "aircraft": "Airbus A400M Atlas"}
    assert AnnouncementWording(LONDON, NOWHERE).text(raf) == "Royal Air Force, Airbus A400M Atlas."


@pytest.fixture
def fake_piper():
    server = socket.create_server(("127.0.0.1", 0))
    received = []

    def serve():
        connection, _ = server.accept()
        with connection:
            received.append(json.loads(connection.makefile("rb").readline()))
            start = json.dumps({"rate": 22050, "width": 2, "channels": 1}).encode()
            connection.sendall((json.dumps({"type": "audio-start", "data_length": len(start)}) + "\n").encode() + start)
            for chunk in (b"\x01\x00" * 10, b"\x02\x00" * 10):
                connection.sendall(
                    (json.dumps({"type": "audio-chunk", "data": {"rate": 22050}, "payload_length": len(chunk)}) + "\n").encode() + chunk
                )
            connection.sendall((json.dumps({"type": "audio-stop"}) + "\n").encode())

    threading.Thread(target=serve, daemon=True).start()
    yield server.getsockname()[1], received
    server.close()


def test_wyoming_client_turns_the_audio_events_into_a_wav(fake_piper):
    port, received = fake_piper
    clip = WyomingSpeech("127.0.0.1", port, 5).synthesize("hello")
    assert received == [{"type": "synthesize", "data": {"text": "hello"}}]
    with wave.open(io.BytesIO(clip)) as audio:
        assert (audio.getframerate(), audio.getsampwidth(), audio.getnchannels(), audio.getnframes()) == (22050, 2, 1, 20)


def test_wyoming_client_reports_an_unreachable_server():
    unused = socket.create_server(("127.0.0.1", 0))
    port = unused.getsockname()[1]
    unused.close()
    with pytest.raises(SpeechFailed):
        WyomingSpeech("127.0.0.1", port, 1).synthesize("hello")


def test_the_announcement_says_where_the_plane_will_be_when_the_words_are_heard(tmp_path):
    synth = CountingSynth()
    # Heading west at 240 knots, 0.12 km a second, from 3 km east of home: overhead in 24 seconds.
    card = {**CARD, "lat": HOME.lat, "lon": HOME.lon + 3 / 69.36, "trackDeg": 270.0, "speedKt": 240.0, "overheadInSeconds": 24}
    timing = SpeechTiming(chars_per_second=10, making_ratio=0, launch_start_seconds=10, showing_start_seconds=1)
    arrival = SpokenArrival(HOME, 0.5)
    announcer = Announcer(
        AnnouncementWording(LONDON, SpokenWhereabouts(HOME)),
        arrival,
        timing,
        SpeechClips(KeptFiles(tmp_path, "speech/", 5, ".wav"), synth),
        Announced(),
        LOG,
    )
    announcer.speech_for(card)
    # The lead-in "F R, 2 0 S W, from Alicante, to London Stansted" is 46 characters, 4.6 seconds,
    # after a 10 second launch: about 14.6 seconds, or 1.8 km, so 1.2 km away when it is said.
    # The whole announcement is heard about 25 seconds from now, by when it is overhead.
    assert synth.texts[-1] == (
        "F R, 2 0 S W, from Alicante, to London Stansted, 1.2 kilometres away, in an Easterly direction, heading West. It's overhead now."
    )
    announcer.speech_for({**card, "hex": "next", "callsign": "EZY1"})
    # The next plane takes over a card already showing, so it starts after 1 second, not 10:
    # 5.6 seconds to the distance, 0.7 km, and about 16 to the end, still 1 km out.
    assert synth.texts[-1].endswith("2.3 kilometres away, in an Easterly direction, heading West. It will be overhead in a few seconds.")


def test_ahead_moves_the_plane_along_its_track_and_counts_down_to_overhead():
    card = {"lat": HOME.lat, "lon": HOME.lon, "trackDeg": 0.0, "speedKt": 240.0, "overheadInSeconds": 30}
    later = ahead(card, 10)
    assert later["lat"] == pytest.approx(HOME.lat + 1.2347 / 110.574, abs=1e-5)
    assert later["lon"] == pytest.approx(HOME.lon)
    assert later["overheadInSeconds"] == 20
    assert ahead(card, 40)["overheadInSeconds"] is None
    assert ahead({**card, "trackDeg": None}, 10)["lat"] == HOME.lat


def serve_lines(lines):
    server = socket.create_server(("127.0.0.1", 0))

    def serve():
        connection, _ = server.accept()
        with connection:
            connection.makefile("rb").readline()
            for line in lines:
                connection.sendall((json.dumps(line) + "\n").encode())

    threading.Thread(target=serve, daemon=True).start()
    return server


def test_wyoming_client_ignores_events_it_does_not_know_and_reports_a_server_that_hangs_up_early():
    server = serve_lines([{"type": "info"}])
    with pytest.raises(SpeechFailed, match="closed the connection early"):
        WyomingSpeech("127.0.0.1", server.getsockname()[1], 5).synthesize("hello")
    server.close()


def test_wyoming_client_reports_audio_that_never_started():
    server = serve_lines([{"type": "audio-stop"}])
    with pytest.raises(SpeechFailed, match="no audio-start"):
        WyomingSpeech("127.0.0.1", server.getsockname()[1], 5).synthesize("hello")
    server.close()


def test_a_card_that_goes_up_before_its_route_is_known_is_announced_once_it_is(tmp_path):
    synth = CountingSynth()
    announcer = Announcer(
        AnnouncementWording(LONDON, NOWHERE),
        NOWHERE,
        INSTANT,
        SpeechClips(KeptFiles(tmp_path, "speech/", 5, ".wav"), synth),
        Announced(),
        LOG,
    )
    early = {**CARD, "callsign": None, "flightNumber": None, "origin": None, "destination": None}
    assert announcer.speech_for(early) is None
    url = announcer.speech_for(CARD)
    assert url and announcer.speech_for(CARD) == url
    assert len(synth.texts) == 1


def test_a_flight_with_nothing_to_say_is_not_announced(tmp_path):
    synth = CountingSynth()
    announcer = Announcer(
        AnnouncementWording(LONDON, NOWHERE),
        NOWHERE,
        INSTANT,
        SpeechClips(KeptFiles(tmp_path, "speech/", 5, ".wav"), synth),
        Announced(),
        LOG,
    )
    assert announcer.speech_for({**CARD, "callsign": None, "flightNumber": None}) is None
    assert synth.texts == []


def test_silence_has_nothing_to_wind_up_when_a_plane_goes():
    assert Silence().ended() is None


class HeardSynth:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.texts.append(text)
        return b"wav"


def test_a_word_styled_in_capitals_is_said_as_a_word():
    heard = HeardSynth()
    voice = SaidAsWords(heard, {"MAX": "Max"})
    assert voice.synthesize("R Y R, Boeing 737 MAX 8, from Alicante.") == b"wav"
    voice.synthesize("Airbus A320, MAXIMUM, AMAX")
    assert heard.texts == ["R Y R, Boeing 737 Max 8, from Alicante.", "Airbus A320, MAXIMUM, AMAX"]


def test_with_no_words_to_change_the_text_goes_through_as_it_is():
    heard = HeardSynth()
    SaidAsWords(heard, {}).synthesize("Boeing 737 MAX 8")
    assert heard.texts == ["Boeing 737 MAX 8"]


def test_an_airbus_type_is_said_the_way_people_who_fly_them_say_it():
    heard = HeardSynth()
    voice = AirbusNumbersSaid(heard)
    assert voice.synthesize("E Z Y, Airbus A320neo, from Geneva.") == b"wav"
    voice.synthesize("Airbus A350-1000, Airbus A220-300, Airbus A300, Airbus A321neo")
    voice.synthesize("Boeing 737 MAX 8, A3200, BA320")
    assert heard.texts == [
        "E Z Y, Airbus A 3 20 neo, from Geneva.",
        "Airbus A 3 50 1000, Airbus A 2 20 300, Airbus A 3 hundred, Airbus A 3 21 neo",
        "Boeing 737 MAX 8, A3200, BA320",
    ]


def test_a_boeing_type_is_said_a_digit_at_a_time():
    heard = HeardSynth()
    voice = BoeingNumbersSaid(heard)
    assert voice.synthesize("B A W, Boeing 787-9, from Austin.") == b"wav"
    voice.synthesize("Boeing 737 MAX 8, Boeing 777-300ER, Boeing 747")
    voice.synthesize("Embraer E175, 7 4 7, 1787, 707A")
    assert heard.texts == [
        "B A W, Boeing 7 8 7 9, from Austin.",
        "Boeing 7 3 7 MAX 8, Boeing 7 7 7 300ER, Boeing 7 4 7",
        "Embraer E175, 7 4 7, 1787, 707A",
    ]


def test_a_notable_aircraft_says_who_it_belongs_to():
    wording = AnnouncementWording(LONDON, NOWHERE)
    private = {"callsign": "GPOPS", "aircraft": "Dassault Falcon 7X", "owner": "A Pop Star"}
    assert wording.text(private) == "G P O P S, Dassault Falcon 7X, belonging to A Pop Star."
    routed = {**CARD, "owner": "A Football Club"}
    assert wording.text(routed) == "F R, 2 0 S W, from Alicante, to London Stansted, belonging to A Football Club."
