from flights_watcher.audible import FEET_PER_KM, AnyOf, FamousOwners, HeardFromTheGround, SpokenServices

IN_ZONE = {"destination": None, "altitudeFt": 4000, "verticalRateFpm": None, "overheadInSeconds": None, "distanceKm": 1.0}
HEARD = HeardFromTheGround(2, 1.5)


def test_a_low_flight_in_the_zone_is_heard_whether_or_not_its_route_is_known():
    assert HEARD.includes(IN_ZONE)
    assert HEARD.includes({**IN_ZONE, "destination": {"code": "STN"}})
    assert HEARD.includes({**IN_ZONE, "distanceKm": 1.5})


def test_a_flight_with_no_height_is_not():
    assert not HEARD.includes({**IN_ZONE, "altitudeFt": None})


def test_a_flight_high_over_home_is_not_heard():
    assert not HEARD.includes({**IN_ZONE, "altitudeFt": round(2 * FEET_PER_KM) + 1})


def test_a_low_flight_outside_the_zone_and_not_coming_into_it_is_not_heard():
    assert not HEARD.includes({**IN_ZONE, "distanceKm": 1.6})
    assert not HEARD.includes({key: value for key, value in IN_ZONE.items() if key != "distanceKm"})


def test_a_plane_on_its_way_is_judged_by_its_height_when_it_passes():
    on_its_way = {**IN_ZONE, "distanceKm": 12.0, "overheadInSeconds": 60}
    climbing = {**on_its_way, "altitudeFt": 5000, "verticalRateFpm": 3000}
    descending = {**on_its_way, "altitudeFt": 8000, "verticalRateFpm": -2000}
    assert not HEARD.includes(climbing)
    assert HEARD.includes(descending)


def test_only_the_services_named_are_always_heard():
    services = SpokenServices(("ambulance", "police"))
    assert services.includes({"service": "police"})
    assert services.includes({"service": "ambulance"})
    assert not services.includes({"service": "military"})
    assert not services.includes({"service": None, "owner": "A Pop Star"})


def test_any_of_the_rules_will_do():
    rules = AnyOf([SpokenServices(("police",)), HEARD])
    assert rules.includes({"service": "police"})
    assert rules.includes(IN_ZONE)
    assert not rules.includes({**IN_ZONE, "altitudeFt": 9000})


def test_a_famous_owners_plane_is_always_heard():
    assert FamousOwners().includes({"owner": "A Pop Star"})
    assert not FamousOwners().includes({"owner": None})
    assert not FamousOwners().includes({})
