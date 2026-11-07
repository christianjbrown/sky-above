import logging

import pytest

from fakes import FakeClock, FakeHttp, http_error
from flights_watcher.caching import TtlCache
from flights_watcher.lookups import LookupFailed
from flights_watcher.portraits import CachedPortraits, NoPortraits, WikipediaPortraits

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
    assert NoPortraits().portrait("A Pop Star") is None


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
