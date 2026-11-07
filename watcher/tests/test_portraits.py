import logging

import pytest

from fakes import FakeClock, FakeHttp, http_error
from flights_watcher.caching import TtlCache
from flights_watcher.lookups import LookupFailed
from flights_watcher.portraits import CachedPortraits, FirstPortrait, LocalPortraits, WikipediaPortraits, file_name

BASE = "https://wiki.example/api/rest_v1/"
FREE = "https://upload.example/wikipedia/commons/thumb/a/ab/A_Pop_Star.jpg/330px-A_Pop_Star.jpg"
LOGO = "https://upload.example/wikipedia/en/thumb/2/2d/A_Club_crest.svg/330px-A_Club_crest.svg.png"


def summary(article):
    return f"https://wiki.example/api/rest_v1/page/summary/{article}"


def test_the_portrait_is_the_free_lead_picture_of_their_article():
    missing = http_error(404)
    http = FakeHttp(
        {
            summary("A_Pop_Star"): {"type": "standard", "thumbnail": {"source": FREE}},
            summary("A_Football_Club"): {"type": "standard", "thumbnail": {"source": LOGO}},
            summary("Somebody"): {"type": "disambiguation", "thumbnail": {"source": FREE}},
            summary("A_Shy_Person"): {"type": "standard"},
            summary("A_King_%28monarch%29"): {"type": "standard", "thumbnail": {"source": FREE}},
            summary("Strange"): ["not", "a", "page"],
            summary("Nobody"): missing,
        }
    )
    portraits = WikipediaPortraits(BASE, http)
    assert portraits.portrait("A Pop Star") == FREE
    assert portraits.portrait("A Football Club") is None
    assert portraits.portrait("Somebody") is None
    assert portraits.portrait("A Shy Person") is None
    assert portraits.portrait("A King (monarch)") == FREE
    assert portraits.portrait("Strange") is None
    assert portraits.portrait("Nobody") is None
    missing.close()


def test_a_service_that_cannot_be_asked_is_a_failed_lookup():
    broken = http_error(500)
    for error in (broken, OSError("offline"), ValueError("not json")):
        with pytest.raises(LookupFailed):
            WikipediaPortraits(BASE, FakeHttp({summary("A_Pop_Star"): error})).portrait("A Pop Star")
    broken.close()


def test_portraits_are_asked_for_once_and_failures_count_as_none_for_a_while(caplog):
    class Portraits:
        def __init__(self):
            self.asked = []

        def portrait(self, article):
            self.asked.append(article)
            if article == "Down":
                raise LookupFailed("offline")
            return FREE

    clock, inner = FakeClock(), Portraits()
    cached = CachedPortraits(inner, TtlCache(clock, 3600, 10, 60), logging.getLogger("test"))
    assert cached.portrait("A Pop Star") == FREE
    assert cached.portrait("A Pop Star") == FREE
    assert cached.portrait("Down") is None
    assert cached.portrait("Down") is None
    assert inner.asked == ["A Pop Star", "Down"]
    assert "portrait lookup for Down failed" in caplog.text
    clock.seconds = 61
    cached.portrait("Down")
    assert inner.asked == ["A Pop Star", "Down", "Down"]


def test_pictures_kept_on_the_pi_are_found_by_the_owner_s_name(tmp_path):
    (tmp_path / "a-football-club.png").write_bytes(b"png")
    (tmp_path / "a-king-monarch.svg").write_text("<svg/>")
    (tmp_path / "a-pop-star.gif").write_bytes(b"gif")
    local = LocalPortraits(tmp_path, "portraits/")
    assert local.portrait("A Football Club") == "portraits/a-football-club.png"
    assert local.portrait("A King (monarch)") == "portraits/a-king-monarch.svg"
    assert local.portrait("A Pop Star") is None
    assert file_name("  Leicester City F.C. ") == "leicester-city-f-c"


def test_the_first_place_with_a_picture_wins():
    class Fixed:
        def __init__(self, answers):
            self.answers = answers

        def portrait(self, article):
            return self.answers.get(article)

    first = FirstPortrait([Fixed({"A Football Club": "portraits/club.png"}), Fixed({"A Football Club": FREE, "A Pop Star": FREE})])
    assert first.portrait("A Football Club") == "portraits/club.png"
    assert first.portrait("A Pop Star") == FREE
    assert first.portrait("Nobody") is None
    assert FirstPortrait([]).portrait("A Pop Star") is None
