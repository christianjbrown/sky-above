import logging
from datetime import datetime, timedelta

from test_following import LEAVES, StubSchedules, builder, flight

from fakes import FakeClock
from flights_watcher.estimate import (
    DepartureEstimator,
    EstimatedFollowedFlights,
    RecentBlockTimes,
    TurnaroundRule,
    TurnaroundsByType,
)
from flights_watcher.following import Estimate, Followed
from flights_watcher.lookups import Airport

LOG = logging.getLogger("test")
TURNAROUNDS = TurnaroundsByType(
    [TurnaroundRule(("B77", "A35"), timedelta(minutes=75)), TurnaroundRule(("E1", "AT"), timedelta(minutes=25))],
    timedelta(minutes=35),
)
BASEL = Airport("BSL", "Basel-Mulhouse", "Basel")
# The plane's inbound leg from Basel, timetabled to land in good time for LEAVES at 16:25.
INBOUND = {
    "fa_flight_id": "BAW759-1",
    "ident": "BA759",
    "origin": BASEL,
    "destination": Airport("LHR", "Heathrow", "London"),
    "scheduled_out": LEAVES - timedelta(hours=2, minutes=30),
    "scheduled_in": LEAVES - timedelta(hours=1),
}


class Blocks:
    def __init__(self, **typical: int) -> None:
        self.typical_minutes = typical

    def typical(self, ident):
        minutes = self.typical_minutes.get(ident)
        return timedelta(minutes=minutes) if minutes is not None else None


def estimator(now: datetime = LEAVES - timedelta(hours=3), **typical: int) -> DepartureEstimator:
    return DepartureEstimator(Blocks(**typical), TURNAROUNDS, FakeClock(now))


def leg(**fields):
    return flight(**{**INBOUND, **fields})


def test_turnarounds_go_by_the_type_of_plane():
    assert TURNAROUNDS.shortest("B77W") == timedelta(minutes=75)
    assert TURNAROUNDS.shortest("E190") == timedelta(minutes=25)
    assert TURNAROUNDS.shortest("A319") == timedelta(minutes=35)
    assert TURNAROUNDS.shortest(None) == timedelta(minutes=35)


def test_an_inbound_leg_due_out_on_time_is_flown_in_its_usual_time_and_turned_round():
    estimate = estimator(BA759=80).estimate(Followed(flight(), [leg()], None))
    arrives = INBOUND["scheduled_out"] + timedelta(minutes=80)
    assert estimate == Estimate(arrives, timedelta(minutes=35), arrives + timedelta(minutes=35))


def test_without_a_history_the_timetabled_block_time_stands_in():
    estimate = estimator().estimate(Followed(flight(), [leg()], None))
    assert estimate.inbound_arrives == INBOUND["scheduled_in"]


def test_a_leg_still_on_the_ground_after_it_was_due_leaves_no_sooner_than_now():
    now = INBOUND["scheduled_out"] + timedelta(minutes=50)
    estimate = estimator(now, BA759=90).estimate(Followed(flight(), [leg()], None))
    assert estimate.inbound_arrives == now + timedelta(minutes=90)


def test_a_late_leg_before_holds_up_the_inbound_one():
    before = flight(
        fa_flight_id="BAW758-1",
        ident="BA758",
        scheduled_out=LEAVES - timedelta(hours=5),
        scheduled_in=LEAVES - timedelta(hours=3, minutes=15),
        actual_out=LEAVES - timedelta(hours=4, minutes=30),
        actual_in=LEAVES - timedelta(hours=2, minutes=20),
    )
    estimate = estimator(BA759=90).estimate(Followed(flight(), [leg(), before], None))
    # In from the leg before at 14:05, 35 minutes to turn round, so off from Basel at 14:40.
    assert estimate.inbound_arrives == LEAVES - timedelta(hours=2, minutes=20) + timedelta(minutes=35 + 90)


def test_an_inbound_leg_in_the_air_keeps_flightawares_own_arrival_time():
    airborne = leg(actual_out=INBOUND["scheduled_out"], estimated_in=LEAVES - timedelta(minutes=20))
    estimate = estimator(BA759=80).estimate(Followed(flight(), [airborne], None))
    assert estimate.inbound_arrives == LEAVES - timedelta(minutes=20)
    assert estimate.ready == LEAVES + timedelta(minutes=15)


def test_nothing_is_estimated_once_the_flight_has_left_or_with_no_earlier_leg():
    assert estimator().estimate(Followed(flight(actual_out=LEAVES), [leg()], None)) is None
    assert estimator().estimate(Followed(flight(), [], None)) is None


def test_recent_block_times_are_the_middle_of_what_the_flight_actually_took_and_kept_a_while(caplog):
    days = [
        leg(fa_flight_id=f"BAW759-{n}", actual_out=LEAVES - timedelta(days=n), actual_in=LEAVES - timedelta(days=n) + timedelta(minutes=m))
        for n, m in ((1, 80), (2, 95), (3, 85))
    ]
    schedules = StubSchedules(*days, leg(fa_flight_id="BAW759-today"))
    clock = FakeClock(LEAVES)
    blocks = RecentBlockTimes(schedules, 3600, clock, LOG)
    assert blocks.typical("BA759") == timedelta(minutes=85)
    clock.seconds = 1800
    blocks.typical("BA759")
    assert schedules.asked == ["flights BA759"]
    clock.seconds = 4000
    schedules.failing = True
    assert blocks.typical("BA759") == timedelta(minutes=85)
    assert "could not look up recent BA759 flights" in caplog.text


def test_the_estimate_rides_along_with_the_followed_flight():
    class On:
        def current(self, aircraft):
            return Followed(flight(), [leg()], None)

    followed = EstimatedFollowedFlights(On(), estimator(BA759=80)).current([])
    assert followed.estimate is not None


def test_the_card_takes_our_estimate_when_it_is_later_than_the_airlines_and_says_why():
    ready = LEAVES + timedelta(minutes=25)
    followed = Followed(
        flight(estimated_in=LEAVES + timedelta(minutes=110)),
        [leg()],
        None,
        Estimate(LEAVES - timedelta(minutes=10), timedelta(minutes=35), ready),
    )
    message = builder().build(followed)
    card = message["flight"]
    assert card["departsAt"] == "2027-03-12T16:50:00Z"
    assert card["airlineDepartsAt"] == "2027-03-12T16:25:00Z"
    assert card["departureEstimate"] == "ours"
    assert card["departureDelayMinutes"] == 25
    assert card["arrivesAt"] == "2027-03-12T18:40:00Z"
    assert message["reason"] == "Its plane isn't due in from Basel until 16:15"


def test_the_card_keeps_the_airlines_time_when_ours_is_no_later():
    followed = Followed(
        flight(estimated_out=LEAVES + timedelta(minutes=30)),
        [leg()],
        None,
        Estimate(LEAVES - timedelta(minutes=60), timedelta(minutes=35), LEAVES - timedelta(minutes=25)),
    )
    card = builder().build(followed)["flight"]
    assert card["departsAt"] == "2027-03-12T16:55:00Z"
    assert card["departureEstimate"] == "airline"


def test_an_inbound_leg_in_the_air_without_an_arrival_time_is_flown_from_when_it_left():
    airborne = leg(actual_out=INBOUND["scheduled_out"] + timedelta(minutes=10))
    estimate = estimator(BA759=80).estimate(Followed(flight(), [airborne], None))
    assert estimate.inbound_arrives == INBOUND["scheduled_out"] + timedelta(minutes=90)


def test_an_inbound_leg_nothing_is_known_about_leaves_the_plane_without_an_estimate():
    unknown = leg(scheduled_out=None, scheduled_in=None)
    assert estimator().estimate(Followed(flight(), [unknown], None)) is None


def test_no_followed_flight_means_no_estimate():
    class Off:
        def current(self, aircraft):
            return None

    assert EstimatedFollowedFlights(Off(), estimator()).current([]) is None
