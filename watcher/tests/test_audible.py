from flights_watcher.audible import FEET_PER_KM, AnyOf, HeardFromTheGround, SpecialAircraft

GOING = {"destination": {"code": "STN"}, "altitudeFt": 4000, "verticalRateFpm": None, "overheadInSeconds": None}
HEARD = HeardFromTheGround(5)


def test_a_flight_going_somewhere_known_and_low_is_heard():
    assert HEARD.includes(GOING)


def test_a_flight_with_no_destination_or_no_height_is_not():
    assert not HEARD.includes({**GOING, "destination": None})
    assert not HEARD.includes({**GOING, "altitudeFt": None})


def test_a_flight_high_over_home_is_not_heard():
    assert not HEARD.includes({**GOING, "altitudeFt": round(5 * FEET_PER_KM) + 1})


def test_a_plane_on_its_way_is_judged_by_its_height_when_it_passes():
    climbing = {**GOING, "altitudeFt": 14000, "verticalRateFpm": 3000, "overheadInSeconds": 60}
    descending = {**GOING, "altitudeFt": 18000, "verticalRateFpm": -2000, "overheadInSeconds": 60}
    assert not HEARD.includes(climbing)
    assert HEARD.includes(descending)


def test_services_and_famous_owners_are_always_special():
    special = SpecialAircraft(("ambulance", "police", "military"))
    assert special.includes({"service": "police"})
    assert special.includes({"service": None, "owner": "A Pop Star"})
    assert not special.includes({"service": None, "owner": None})
    assert not special.includes({"service": "coastguard"})


def test_any_of_the_rules_will_do():
    rules = AnyOf([SpecialAircraft(("police",)), HEARD])
    assert rules.includes({"service": "police"})
    assert rules.includes(GOING)
    assert not rules.includes({**GOING, "destination": None})
