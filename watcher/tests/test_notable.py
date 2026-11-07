import logging
import os
import threading
from datetime import timedelta

import pytest

from fakes import FakeClock, plane
from flights_watcher.notable import (
    NAMED,
    InBackground,
    LocalText,
    MirroredText,
    Notable,
    NotableAircraft,
    NoText,
    OwnedCards,
    Owner,
    ThreadStarter,
    owner_names,
    plane_alert_table,
)
from flights_watcher.zone import Sighting

LOG = logging.getLogger("test")
URL = "https://example.com/plane-alert-db.csv"
# Made-up aircraft in plane-alert-db's columns.
TABLE = """$ICAO,$Registration,$Operator,$Type,$ICAO Type,#CMPG,$Tag 1,$#Tag 2,$#Tag 3,Category,$#Link
ABC123,N123AB,A Pop Star,Dassault Falcon 7X,FA7X,Civ,Bizjet,Music,Tours,Don't you know who I am?,
4CA001,G-ABCD,A Football Club,Boeing 737-BBJ,B737,Civ,Bizjet,Football,Away Days,Football,
43C001,ZZ999,Royal Air Force,Airbus A400M,A400,Mil,Cargo,Tactical,Atlas,RAF,
000000,,,Mystery,,Civ,,,,Football,
"""


class Now:
    def __init__(self, value):
        self.it = value

    def value(self):
        return self.it


class TextHttp:
    def __init__(self, answer):
        self.answer = answer
        self.asked = 0

    def get_text(self, url):
        assert url == URL
        self.asked += 1
        if isinstance(answer := self.answer, BaseException):
            raise answer
        return answer


class Later:
    """Holds the work it is handed until told to run it."""

    def __init__(self):
        self.waiting = []

    def start(self, work):
        self.waiting.append(work)

    def run(self):
        work, self.waiting = self.waiting, []
        for job in work:
            job()


def test_the_list_gives_each_aircraft_in_the_chosen_categories_by_hex():
    table = plane_alert_table(TABLE, ("Don't you know who I am?", "Football"))
    assert table == {
        "abc123": Notable("A Pop Star", "Don't you know who I am?"),
        "4ca001": Notable("A Football Club", "Football"),
    }
    assert plane_alert_table("", ("Football",)) == {}


def test_the_names_file_says_who_each_registration_belongs_to():
    text = (
        "# who really owns them\n\nN123AB  A Pop Star\ng-abcd A Football Club\nG-NONAME\n"
        "G-ROYL The King | A King (monarch)\nG-BAR | Nobody\n"
    )
    assert owner_names(text) == {
        "N123AB": Owner("A Pop Star"),
        "GABCD": Owner("A Football Club"),
        "GROYL": Owner("The King", "A King (monarch)"),
    }


def test_the_names_file_comes_first_and_can_add_planes_the_list_leaves_out():
    table = Now({"abc123": Notable("Island Jets Inc", "Don't you know who I am?"), "4ca001": Notable("A Football Club", "Football")})
    notables = NotableAircraft(table, Now({"N123AB": Owner("A Pop Star", "A Pop Star (singer)"), "GEUYM": Owner("A Racing Driver")}))
    assert notables.of(plane("ABC123", registration="N123AB")) == Notable("A Pop Star", "Don't you know who I am?", "A Pop Star (singer)")
    assert notables.of(plane("4ca001", registration="G-ABCD")) == Notable("A Football Club", "Football")
    assert notables.of(plane("4ca7b5", registration="G-EUYM")) == Notable("A Racing Driver", NAMED)
    assert notables.of(plane("4ca7b6", registration=None)) is None


def test_cards_say_who_a_notable_plane_belongs_to():
    class Cards:
        def card(self, sighting):
            return {"hex": sighting.aircraft.hex}

    class Notables:
        def of(self, aircraft):
            return Notable("A Pop Star", "Don't you know who I am?") if aircraft.hex == "abc123" else None

    class Portraits:
        def portrait(self, article):
            return f"https://example.com/{article}.jpg"

    cards = OwnedCards(Cards(), Notables(), Portraits())
    assert cards.card(Sighting(plane("abc123"), 1.0)) == {
        "hex": "abc123",
        "owner": "A Pop Star",
        "ownerPortrait": "https://example.com/A Pop Star.jpg",
    }
    assert cards.card(Sighting(plane("def456"), 1.0)) == {"hex": "def456", "owner": None, "ownerPortrait": None}


def test_an_owner_is_looked_up_by_their_article_when_it_has_another_name():
    assert Notable("The King", "Royal Aircraft", "A King (monarch)").about == "A King (monarch)"
    assert Notable("A Pop Star", "Don't you know who I am?").about == "A Pop Star"


def test_a_slow_value_is_got_in_the_background_and_again_when_it_is_due():
    clock, later, loads = FakeClock(), Later(), iter(["first", "second"])
    value = InBackground(lambda: next(loads), "", clock, 60, later)
    assert value.value() == ""
    assert value.value() == ""
    assert len(later.waiting) == 1
    later.run()
    assert value.value() == "first"
    clock.seconds = 59
    assert value.value() == "first"
    assert later.waiting == []
    clock.seconds = 60
    value.value()
    later.run()
    assert value.value() == "second"


def test_a_failed_load_keeps_the_last_value_and_tries_again_when_it_is_due():
    clock, later = FakeClock(), Later()

    def fail():
        raise RuntimeError("down")

    value = InBackground(fail, "nothing", clock, 60, later)
    value.value()
    with pytest.raises(RuntimeError):
        later.run()
    assert value.value() == "nothing"
    clock.seconds = 60
    value.value()
    assert len(later.waiting) == 1


def test_background_work_runs_on_a_thread():
    done = threading.Event()
    ThreadStarter().start(done.set)
    assert done.wait(5)


def test_a_local_file_may_not_be_there(tmp_path):
    names = tmp_path / "names.txt"
    assert LocalText(names).text() is None
    names.write_text("N123AB A Pop Star\n")
    assert LocalText(names).text() == "N123AB A Pop Star\n"
    assert NoText().text() is None


def test_the_list_is_fetched_once_and_again_when_it_is_old(tmp_path):
    clock, http, copy = FakeClock(), TextHttp(TABLE), tmp_path / "state" / "plane-alert-db.csv"
    mirrored = MirroredText(URL, copy, 3600, http, clock, LOG)
    assert mirrored.text() == TABLE
    assert mirrored.text() == TABLE
    assert http.asked == 1
    fresh = clock.now().timestamp()
    os.utime(copy, (fresh - 3600, fresh - 3600))
    http.answer = "changed"
    assert mirrored.text() == "changed"
    assert http.asked == 2


def test_when_the_list_cannot_be_fetched_the_copy_stands_in(tmp_path, caplog):
    clock, copy = FakeClock(), tmp_path / "plane-alert-db.csv"
    assert MirroredText(URL, copy, 3600, TextHttp(OSError("offline")), clock, LOG).text() is None
    copy.write_text(TABLE)
    old = (clock.now() - timedelta(days=2)).timestamp()
    os.utime(copy, (old, old))
    assert MirroredText(URL, copy, 3600, TextHttp(ValueError("not a web address")), clock, LOG).text() == TABLE
    assert "could not fetch" in caplog.text
