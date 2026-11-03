import logging
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from fakes import FakeClock, FakeHttp, plane
from flights_watcher.followed_card import FollowedCardBuilder
from flights_watcher.followed_list import FollowedEntry, FollowedListFile
from flights_watcher.following import Estimate, Followed, FollowedFlights, FollowTiming
from flights_watcher.lookups import Airport, LookupFailed
from flights_watcher.naming import AirportCities
from flights_watcher.schedules import AeroApiSchedules, Flight, Position
from flights_watcher.standby import FollowedStandby, NothingOnStandby

LOG = logging.getLogger("test")
UTC = UTC
API = "https://aeroapi.test"
TIMING = FollowTiming(
    lead=timedelta(hours=4),
    tail=timedelta(minutes=30),
    before_showing_every=6 * 3600,
    hours_to_go_every=600,
    last_hour_every=300,
    under_way_every=600,
    earlier_leg_every=600,
    position_every=180,
    not_found_every=1800,
)
LEAVES = datetime(2027, 3, 12, 16, 25, tzinfo=UTC)


def flight(**fields) -> Flight:
    base = {
        "fa_flight_id": "BAW4321-1",
        "ident": "BA4321",
        "operator": "BAW",
        "origin": Airport("LHR", "Heathrow", "London"),
        "destination": Airport("BER", "Brandenburg", "Berlin"),
        "origin_timezone": "Europe/London",
        "destination_timezone": "Europe/Berlin",
        "scheduled_out": LEAVES,
        "estimated_out": None,
        "actual_out": None,
        "actual_off": None,
        "estimated_on": None,
        "actual_on": None,
        "scheduled_in": LEAVES + timedelta(minutes=110),
        "estimated_in": None,
        "actual_in": None,
        "gate_origin": None,
        "terminal_origin": "5",
        "gate_destination": None,
        "terminal_destination": None,
        "baggage_claim": None,
        "status": "Scheduled",
        "cancelled": False,
        "diverted": False,
        "registration": "G-EUPR",
        "aircraft_type": "A319",
        "inbound_id": None,
    }
    base.update(fields)
    return Flight(**base)


class StubList:
    def __init__(self, *entries: FollowedEntry) -> None:
        self.list = list(entries)

    def entries(self):
        return self.list


class StubSchedules:
    def __init__(self, *flights: Flight) -> None:
        self.by_id = {f.fa_flight_id: f for f in flights}
        self.positions: dict[str, Position] = {}
        self.asked: list[str] = []
        self.failing = False

    def flights(self, ident):
        self.asked.append(f"flights {ident}")
        self._maybe_fail()
        return [f for f in self.by_id.values() if f.ident == ident]

    def flight(self, fa_flight_id):
        self.asked.append(f"flight {fa_flight_id}")
        self._maybe_fail()
        return self.by_id.get(fa_flight_id)

    def position(self, fa_flight_id):
        self.asked.append(f"position {fa_flight_id}")
        self._maybe_fail()
        return self.positions.get(fa_flight_id)

    def _maybe_fail(self):
        if self.failing:
            raise LookupFailed("down")


def tracker(schedules: StubSchedules, at: datetime, *entries: FollowedEntry):
    clock = FakeClock(at)
    entries = entries or (FollowedEntry(date(2027, 3, 12), "BA4321"),)
    return FollowedFlights(StubList(*entries), schedules, TIMING, clock, LOG), clock


def test_the_list_file_reads_dates_and_flight_numbers_and_skips_the_rest(tmp_path, caplog):
    path = tmp_path / "flights.txt"
    path.write_text("# ours\n2027-03-01 ba2468\n\n2027-03-12 BA4321  # Berlin\nnot a flight\n")
    followed = FollowedListFile(path, LOG)
    assert followed.entries() == [FollowedEntry(date(2027, 3, 1), "BA2468"), FollowedEntry(date(2027, 3, 12), "BA4321")]
    followed.entries()
    assert caplog.text.count("not a date and a flight number") == 1
    assert FollowedListFile(tmp_path / "missing.txt", LOG).entries() == []


def test_aeroapi_flights_come_back_with_their_times_gates_and_inbound_leg():
    raw = {
        "fa_flight_id": "BAW4321-1",
        "ident": "BAW4321",
        "ident_iata": "BA4321",
        "operator_icao": "BAW",
        "origin": {"code_iata": "LHR", "city": "London", "name": "Heathrow", "timezone": "Europe/London"},
        "destination": {"code_iata": "BER", "city": "Berlin", "name": "Brandenburg", "timezone": "Europe/Berlin"},
        "scheduled_out": "2027-03-12T16:25:00Z",
        "estimated_out": "2027-03-12T16:40:00Z",
        "gate_origin": "B32",
        "terminal_origin": "5",
        "baggage_claim": "7",
        "registration": "G-EUPR",
        "inbound_fa_flight_id": "BAW4320-1",
        "cancelled": False,
    }
    http = FakeHttp(
        {
            f"{API}/flights/BA4321?max_pages=1": {"flights": [raw]},
            f"{API}/flights/BAW4321-1/position": {
                "last_position": {
                    "latitude": 52.1,
                    "longitude": 4.2,
                    "altitude": 350,
                    "groundspeed": 440,
                    "heading": 95,
                    "timestamp": "2027-03-12T17:10:00Z",
                }
            },
        }
    )
    schedules = AeroApiSchedules(API, http)
    [found] = schedules.flights("BA4321")
    assert found.ident == "BA4321" and found.gate_origin == "B32" and found.inbound_id == "BAW4320-1"
    assert found.departs_at == datetime(2027, 3, 12, 16, 40, tzinfo=UTC)
    assert found.destination_timezone == "Europe/Berlin"
    position = schedules.position("BAW4321-1")
    assert position == Position(52.1, 4.2, 95, 35000, 440, datetime(2027, 3, 12, 17, 10, tzinfo=UTC))


def test_flightaware_saying_nowhere_is_no_position():
    nowhere = {"last_position": {"latitude": 0.0, "longitude": 0.0, "altitude": 0, "groundspeed": 0, "update_type": "V"}}
    schedules = AeroApiSchedules(API, FakeHttp({f"{API}/flights/BAW4321-1/position": nowhere}))
    assert schedules.position("BAW4321-1") is None


def test_a_followed_flight_comes_on_four_hours_before_it_is_due_out():
    schedules = StubSchedules(flight())
    early, clock = tracker(schedules, LEAVES - timedelta(hours=4, minutes=1))
    assert early.current([]) is None
    clock.at = LEAVES - timedelta(hours=3, minutes=59)
    clock.seconds = 6 * 3600
    assert early.current([]).flight.ident == "BA4321"


def test_it_stays_until_half_an_hour_after_reaching_the_gate():
    arrived = flight(
        actual_out=LEAVES, actual_off=LEAVES, actual_on=LEAVES + timedelta(minutes=100), actual_in=LEAVES + timedelta(minutes=108)
    )
    schedules = StubSchedules(arrived)
    followed, clock = tracker(schedules, LEAVES + timedelta(minutes=137))
    assert followed.current([]) is not None
    clock.at = LEAVES + timedelta(minutes=139)
    assert followed.current([]) is None


def test_a_cancelled_flight_shows_until_half_an_hour_after_it_was_due_out():
    schedules = StubSchedules(flight(cancelled=True, status="Cancelled"))
    followed, clock = tracker(schedules, LEAVES + timedelta(minutes=29))
    assert followed.current([]) is not None
    clock.at = LEAVES + timedelta(minutes=31)
    assert followed.current([]) is None


def test_only_the_flight_due_out_on_the_listed_day_counts():
    tomorrow = flight(
        fa_flight_id="BAW4321-2", scheduled_out=LEAVES + timedelta(days=1), scheduled_in=LEAVES + timedelta(days=1, minutes=110)
    )
    schedules = StubSchedules(tomorrow)
    followed, _ = tracker(schedules, LEAVES - timedelta(hours=1))
    assert followed.current([]) is None


def test_flightaware_is_asked_more_often_as_departure_nears():
    schedules = StubSchedules(flight())
    followed, clock = tracker(schedules, LEAVES - timedelta(hours=3))
    followed.current([])
    assert schedules.asked == ["flights BA4321"]
    clock.seconds = 599
    followed.current([])
    assert len(schedules.asked) == 1
    clock.seconds = 600
    followed.current([])
    assert schedules.asked[-1] == "flight BAW4321-1"
    clock.at, clock.seconds = LEAVES - timedelta(minutes=50), 899
    followed.current([])
    assert len(schedules.asked) == 2
    clock.seconds = 900
    followed.current([])
    assert len(schedules.asked) == 3


def test_a_failed_lookup_keeps_the_last_answer_and_waits_its_turn():
    schedules = StubSchedules(flight())
    followed, clock = tracker(schedules, LEAVES - timedelta(hours=2))
    followed.current([])
    schedules.failing = True
    clock.seconds = 600
    assert followed.current([]).flight.ident == "BA4321"
    clock.seconds = 700
    followed.current([])
    assert len(schedules.asked) == 2


def test_the_planes_earlier_legs_are_watched_until_it_sets_off():
    two_back = flight(
        fa_flight_id="BAW4319-1", ident="BA4319", origin=Airport("MAD", "Barajas", "Madrid"), actual_out=LEAVES - timedelta(hours=6)
    )
    inbound = flight(fa_flight_id="BAW4320-1", ident="BA4320", origin=Airport("BER", "Brandenburg", "Berlin"), inbound_id="BAW4319-1")
    schedules = StubSchedules(flight(inbound_id="BAW4320-1"), inbound, two_back)
    followed, _ = tracker(schedules, LEAVES - timedelta(hours=2))
    legs = followed.current([]).earlier_legs
    assert [leg.ident for leg in legs] == ["BA4320", "BA4319"]
    schedules.by_id["BAW4321-1"] = flight(inbound_id="BAW4320-1", actual_out=LEAVES)
    departed, _ = tracker(schedules, LEAVES)
    assert departed.current([]).earlier_legs == []


def test_in_the_air_our_own_receiver_places_the_plane_before_flightaware_is_asked():
    flying = flight(actual_out=LEAVES, actual_off=LEAVES + timedelta(minutes=10))
    schedules = StubSchedules(flying)
    schedules.positions["BAW4321-1"] = Position(52.0, 3.0, 90, 30000, 450, LEAVES + timedelta(minutes=40))
    followed, clock = tracker(schedules, LEAVES + timedelta(minutes=20))
    nearby = plane("400abc", lat=51.5, lon=-0.3, registration="GEUPR", altitude_ft=6000)
    assert followed.current([nearby]).position.altitude_ft == 6000
    assert not any(a.startswith("position") for a in schedules.asked)
    assert followed.current([]).position.altitude_ft == 30000
    clock.seconds = 100
    followed.current([])
    assert sum(a.startswith("position") for a in schedules.asked) == 1


def test_our_own_receiver_seeing_it_in_the_air_counts_before_flightaware_has_the_take_off():
    taxiing = flight(actual_out=LEAVES)
    followed, _ = tracker(StubSchedules(taxiing), LEAVES + timedelta(minutes=20))
    climbing = plane("400abc", lat=51.5, lon=-0.3, registration="GEUPR", altitude_ft=3000)
    on_the_ground = plane("400abc", lat=51.47, lon=-0.46, registration="GEUPR", altitude_ft=None, on_ground=True)
    assert followed.current([on_the_ground]).position is None
    seen = followed.current([climbing])
    assert seen.position.altitude_ft == 3000
    assert builder().build(seen)["flight"]["phase"] == "flying"


def test_the_same_plane_flying_in_on_its_earlier_leg_is_not_this_flight():
    followed, _ = tracker(StubSchedules(flight()), LEAVES - timedelta(hours=1))
    arriving = plane("400abc", lat=51.5, lon=-0.3, registration="GEUPR", altitude_ft=3000)
    assert followed.current([arriving]).position is None


def builder() -> FollowedCardBuilder:
    class Names:
        def name(self, icao):
            return {"BAW": "British Airways"}.get(icao)

    return FollowedCardBuilder("Europe/London", [AirportCities({"HEL": "Helsinki"})], Names(), 10, LOG)


def test_the_card_carries_times_in_utc_delays_gates_and_where_each_end_is():
    late = flight(estimated_out=LEAVES + timedelta(minutes=25), gate_origin="B32")
    message = FollowedStandby(StubCurrent(late), builder()).message([])
    card = message["flight"]
    assert message["type"] == "followed" and message["homeTimezone"] == "Europe/London"
    assert card["airline"] == "British Airways" and card["phase"] == "waiting"
    assert card["departsAt"] == "2027-03-12T16:50:00Z" and card["departureDelayMinutes"] == 25
    assert card["destination"]["timezone"] == "Europe/Berlin" and card["gateOrigin"] == "B32"
    assert card["diverted"] is False


def test_the_card_says_when_a_flight_has_been_diverted():
    message = FollowedStandby(StubCurrent(flight(actual_off=LEAVES, diverted=True)), builder()).message([])
    assert message["flight"]["diverted"] is True


def test_a_late_departure_is_put_down_to_the_plane_coming_in_late():
    two_back = flight(
        fa_flight_id="2",
        origin=Airport("MAD", "Barajas", "Madrid"),
        scheduled_in=LEAVES - timedelta(hours=3),
        estimated_in=LEAVES - timedelta(hours=2, minutes=20),
    )
    inbound = flight(
        fa_flight_id="1",
        origin=Airport("HEL", "Vantaa", "Vantaa"),
        scheduled_in=LEAVES - timedelta(minutes=50),
        estimated_in=LEAVES - timedelta(minutes=10),
    )
    late = flight(estimated_out=LEAVES + timedelta(minutes=30))
    cards = builder()
    assert cards.build(_followed(late, [inbound, two_back]))["reason"] == (
        "The plane is running late coming in from Helsinki, after a late start from Madrid"
    )
    on_time_inbound = replace(inbound, estimated_in=inbound.scheduled_in)
    assert cards.build(_followed(late, [on_time_inbound]))["reason"] is None
    assert cards.build(_followed(flight(), [inbound]))["reason"] is None


def test_the_phase_follows_the_flight_from_gate_to_gate():
    cards = builder()
    stages = [
        (flight(), "waiting"),
        (flight(actual_out=LEAVES), "taxiing"),
        (flight(actual_out=LEAVES, actual_off=LEAVES), "flying"),
        (flight(actual_out=LEAVES, actual_off=LEAVES, actual_on=LEAVES), "landed"),
        (flight(actual_out=LEAVES, actual_off=LEAVES, actual_on=LEAVES, actual_in=LEAVES), "arrived"),
        (flight(cancelled=True), "cancelled"),
    ]
    assert [cards.build(_followed(f, []))["flight"]["phase"] for f, _ in stages] == [phase for _, phase in stages]


class StubCurrent:
    def __init__(self, flight_now: Flight) -> None:
        self.flight = flight_now

    def current(self, aircraft):
        return _followed(self.flight, [])


def _followed(flight_now: Flight, legs: list[Flight]) -> Followed:
    return Followed(flight_now, legs, None)


def test_nothing_on_standby_shows_nothing():
    assert NothingOnStandby().message([]) is None


def test_a_late_departure_blames_only_the_plane_coming_in_when_the_one_before_was_on_time():
    inbound = flight(
        fa_flight_id="1",
        origin=Airport("HEL", "Vantaa", "Vantaa"),
        scheduled_in=LEAVES - timedelta(minutes=50),
        estimated_in=LEAVES - timedelta(minutes=10),
    )
    late = flight(estimated_out=LEAVES + timedelta(minutes=30))
    assert builder().build(_followed(late, [inbound]))["reason"] == "The plane is running late coming in from Helsinki"


def test_the_card_leaves_out_what_the_flight_does_not_say():
    card = builder().build(_followed(flight(operator=None, origin=None, scheduled_in=None), []))["flight"]
    assert card["airline"] is None
    assert card["origin"] is None
    assert card["arrivalDelayMinutes"] is None


def test_the_card_goes_without_an_airline_name_when_the_lookup_fails(caplog):
    class Down:
        def name(self, icao):
            raise LookupFailed("down")

    cards = FollowedCardBuilder("Europe/London", [], Down(), 10, LOG)
    assert cards.build(_followed(flight(), []))["flight"]["airline"] is None
    assert "could not name operator BAW: down" in caplog.text


def test_our_estimate_is_not_blamed_for_a_delay_too_small_to_count_as_late():
    followed = Followed(
        flight(),
        [flight(fa_flight_id="1")],
        None,
        Estimate(LEAVES - timedelta(minutes=60), timedelta(minutes=35), LEAVES + timedelta(minutes=5)),
    )
    message = builder().build(followed)
    assert message["flight"]["departureEstimate"] == "ours"
    assert message["reason"] is None


def test_a_list_file_that_cannot_be_read_is_complained_about_once_and_counts_as_empty(tmp_path, caplog):
    unreadable = FollowedListFile(tmp_path, LOG)
    assert unreadable.entries() == []
    assert unreadable.entries() == []
    assert caplog.text.count("cannot read") == 1


def test_a_line_with_an_impossible_date_is_skipped(tmp_path):
    path = tmp_path / "flights.txt"
    path.write_text("2027-13-45 BA4321\n")
    assert FollowedListFile(path, LOG).entries() == []


def test_a_flight_that_loses_its_times_is_no_longer_shown():
    schedules = StubSchedules(flight())
    followed, clock = tracker(schedules, LEAVES - timedelta(hours=2))
    assert followed.current([]) is not None
    schedules.by_id["BAW4321-1"] = flight(scheduled_out=None, scheduled_in=None)
    clock.seconds = 600
    assert followed.current([]) is None


def test_a_flight_flightaware_has_not_heard_of_is_asked_after_again_only_now_and_then():
    schedules = StubSchedules()
    followed, clock = tracker(schedules, LEAVES - timedelta(hours=1))
    assert followed.current([]) is None
    clock.seconds = 1799
    assert followed.current([]) is None
    assert schedules.asked == ["flights BA4321"]
    clock.seconds = 1800
    followed.current([])
    assert len(schedules.asked) == 2


def test_an_earlier_leg_flightaware_cannot_find_ends_the_chain():
    schedules = StubSchedules(flight(inbound_id="missing"))
    followed, _ = tracker(schedules, LEAVES - timedelta(hours=2))
    assert followed.current([]).earlier_legs == []


def test_an_earlier_leg_that_has_landed_is_not_asked_about_again():
    landed = flight(fa_flight_id="BAW4320-1", ident="BA4320", actual_out=LEAVES - timedelta(hours=4), actual_in=LEAVES - timedelta(hours=2))
    schedules = StubSchedules(flight(inbound_id="BAW4320-1"), landed)
    followed, clock = tracker(schedules, LEAVES - timedelta(hours=1))
    followed.current([])
    clock.seconds = 5000
    followed.current([])
    assert schedules.asked.count("flight BAW4320-1") == 1


def test_a_departure_time_in_an_unknown_zone_is_read_as_utc():
    elsewhere = flight(origin_timezone="Nowhere/Land")
    followed, _ = tracker(StubSchedules(elsewhere), LEAVES - timedelta(hours=1))
    assert followed.current([]) is not None


def test_a_flight_without_a_registration_is_never_matched_to_a_plane_in_range():
    taxiing = flight(registration=None, actual_out=LEAVES)
    followed, _ = tracker(StubSchedules(taxiing), LEAVES + timedelta(minutes=20))
    assert followed.current([plane("400abc", registration="GEUPR")]).position is None


def test_other_planes_in_range_are_not_taken_for_the_followed_one():
    taxiing = flight(actual_out=LEAVES)
    followed, _ = tracker(StubSchedules(taxiing), LEAVES + timedelta(minutes=20))
    stranger = plane("400abc", registration="G-OTHR")
    ours = plane("400abd", registration="G-EUPR", altitude_ft=3000)
    assert followed.current([stranger, ours]).position.altitude_ft == 3000


def test_one_flight_is_looked_up_by_its_flightaware_id():
    raw = {"fa_flight_id": "BAW4321-1", "ident_iata": "BA4321", "scheduled_out": "not a time", "actual_out": 12}
    http = FakeHttp({f"{API}/flights/BAW4321-1?ident_type=fa_flight_id": {"flights": [raw]}})
    found = AeroApiSchedules(API, http).flight("BAW4321-1")
    assert found.ident == "BA4321"
    assert found.scheduled_out is None and found.actual_out is None


def test_flightaware_giving_no_last_position_is_no_position():
    schedules = AeroApiSchedules(API, FakeHttp({f"{API}/flights/BAW4321-1/position": {"last_position": None}}))
    assert schedules.position("BAW4321-1") is None
