from fakes import HOME, plane
from flights_watcher.anywhere import AnySpecial, FamousOwner, HeardAnywhere, ServiceKinds
from flights_watcher.naming import MilitaryService
from flights_watcher.notable import Notable
from flights_watcher.zone import Zone


class ByHex:
    def __init__(self, *hexes: str) -> None:
        self._hexes = hexes

    def of(self, aircraft):
        return Notable("A Pop Star", "Celebrity") if aircraft.hex in self._hexes else None


SPECIAL = AnySpecial([ServiceKinds(MilitaryService(), ("military",)), FamousOwner(ByHex("famous"))])


def test_special_aircraft_are_added_after_the_zone_nearest_first():
    finder = HeardAnywhere(Zone(HOME, 3), SPECIAL, HOME)
    planes = [
        plane("far", lat=HOME.lat + 1, military=True),
        plane("famous", lat=HOME.lat + 0.5),
        plane("overhead", lat=HOME.lat + 0.001),
        plane("ordinary", lat=HOME.lat + 0.3),
        plane("landed", lat=HOME.lat + 0.2, military=True, on_ground=True),
        plane("unplaced", location=None, military=True),
    ]
    found = finder.sightings(planes)
    assert [s.aircraft.hex for s in found] == ["overhead", "famous", "far"]
    assert [s.afar for s in found] == [False, True, True]
    assert round(found[1].distance_km) == 56


def test_a_special_plane_in_the_zone_is_not_added_twice():
    finder = HeardAnywhere(Zone(HOME, 3), SPECIAL, HOME)
    found = finder.sightings([plane("famous", lat=HOME.lat + 0.001)])
    assert [(s.aircraft.hex, s.afar) for s in found] == [("famous", False)]
