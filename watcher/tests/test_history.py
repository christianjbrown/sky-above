import logging
import sqlite3
from datetime import UTC, datetime, timedelta, timezone

import pytest

from fakes import FakeClock
from flights_watcher.history import Forgetting, HistoryPage, Kind, Shown, ShownHistory, SqliteShownStore

LOG = logging.getLogger("test")
BST = timezone(timedelta(hours=1))


def card(hex_code="abc123", km=3.0, ft=4000, **extra):
    return {"hex": hex_code, "distanceKm": km, "altitudeFt": ft, **extra}


def planes(*cards):
    return {"type": "planes", "planes": list(cards)}


def shown(hex_code="abc123", at="2026-11-01T12:00:00+00:00", kind=Kind.AIRLINE, owner=None, km=3.0):
    return Shown(hex_code, at, kind, None, None, None, None, None, None, None, None, owner, None, None, km, 4000)


class Kept:
    def __init__(self):
        self.kept = []
        self.forgotten = []

    def keep(self, s):
        self.kept.append(s)

    def forget_airlines_before(self, cutoff):
        self.forgotten.append(cutoff)

    def everything(self):
        return list(self.kept)


def history():
    kept, clock = Kept(), FakeClock(datetime(2026, 7, 1, 13, 0, tzinfo=BST))
    return ShownHistory(kept, clock), kept, clock


def test_a_plane_is_kept_as_soon_as_it_takes_the_card_with_everything_the_card_says():
    recorder, kept, _ = history()
    full = card(
        callsign="EZY12AB",
        flightNumber="U21234",
        registration="G-EZAB",
        aircraft="Airbus A320neo",
        typeCode="A20N",
        airline="easyJet",
        origin={"code": "ALC", "city": "Alicante", "name": "Alicante-Elche"},
        destination={"code": "STN", "name": "London Stansted"},
        emergency={"label": "General emergency"},
    )
    assert recorder.show(planes(full, card("second"))) is False
    assert kept.kept == [
        Shown(
            "abc123",
            "2026-07-01T12:00:00+00:00",
            Kind.AIRLINE,
            "EZY12AB",
            "U21234",
            "G-EZAB",
            "Airbus A320neo",
            "A20N",
            "easyJet",
            "Alicante (ALC)",
            "London Stansted (STN)",
            None,
            None,
            "General emergency",
            3.0,
            4000,
        )
    ]


@pytest.mark.parametrize(
    ("extra", "kind"),
    [
        ({"airline": "easyJet"}, Kind.AIRLINE),
        ({"callsign": "SHT9Q", "airlineCode": "SHT"}, Kind.AIRLINE),
        ({"callsign": "GEUYM", "airlineCode": None}, Kind.PRIVATE_PLANE),
        ({"airline": "Air Ambulance", "service": "ambulance", "helicopter": True}, Kind.AMBULANCE),
        ({"airline": "Police", "service": "police", "helicopter": True}, Kind.POLICE),
        ({"airline": "Royal Air Force", "service": "military"}, Kind.MILITARY),
        ({"airline": "US Navy", "military": True}, Kind.MILITARY),
        ({"helicopter": True}, Kind.PRIVATE_HELICOPTER),
        ({}, Kind.PRIVATE_PLANE),
        ({"airline": "A Charter Airline", "owner": "A Football Club", "ownerCategory": "Football"}, Kind.PRIVATE_PLANE),
        ({"service": "something new", "helicopter": True}, Kind.PRIVATE_HELICOPTER),
    ],
)
def test_each_plane_is_kept_as_a_kind_the_page_can_filter_by(extra, kind):
    recorder, kept, _ = history()
    recorder.show(planes(card(**extra)))
    assert kept.kept[0].kind == kind


def test_a_famous_owner_is_kept_with_what_they_are_listed_as():
    recorder, kept, _ = history()
    recorder.show(planes(card(helicopter=True, owner="A Racing Driver", ownerCategory="Named")))
    assert (kept.kept[0].kind, kept.kept[0].owner, kept.kept[0].owner_category) == (Kind.PRIVATE_HELICOPTER, "A Racing Driver", "Named")


def test_an_airport_with_only_a_code_or_only_a_name_is_kept_as_it_is():
    recorder, kept, _ = history()
    recorder.show(planes(card(origin={"code": "ALC"}, destination={"city": "Paris"})))
    assert (kept.kept[0].origin, kept.kept[0].destination) == ("ALC", "Paris")


def test_the_closest_and_lowest_are_written_once_the_plane_gives_up_the_card():
    recorder, kept, clock = history()
    recorder.show(planes(card(km=3.0, ft=None)))
    recorder.show(planes(card(km=1.2, ft=3000)))
    recorder.show(planes(card(km=2.0, ft=3500)))
    assert len(kept.kept) == 1
    clock.at += timedelta(minutes=2)
    recorder.show(planes(card("def456", km=4.0)))
    assert [(s.hex, s.closest_km, s.lowest_ft) for s in kept.kept] == [("abc123", 3.0, None), ("abc123", 1.2, 3000), ("def456", 4.0, 4000)]
    assert kept.kept[1].shown_at == kept.kept[0].shown_at


def test_a_plane_with_no_height_at_all_keeps_none():
    recorder, kept, _ = history()
    recorder.show(planes(card(ft=None)))
    recorder.show(planes(card(km=1.0, ft=None)))
    recorder.clear()
    assert kept.kept[-1].lowest_ft is None


def test_clearing_writes_the_last_plane_only_when_it_changed_and_a_return_is_a_new_showing():
    recorder, kept, clock = history()
    recorder.show(planes(card()))
    recorder.clear()
    recorder.clear()
    assert len(kept.kept) == 1
    clock.at += timedelta(minutes=30)
    recorder.show(planes(card()))
    assert [s.shown_at for s in kept.kept] == ["2026-07-01T12:00:00+00:00", "2026-07-01T12:30:00+00:00"]


def test_messages_without_a_plane_are_not_kept():
    recorder, kept, _ = history()
    assert recorder.show({"type": "followed", "flight": {"ident": "BA1"}}) is False
    assert recorder.show(planes()) is False
    assert kept.kept == []


def test_the_store_keeps_and_replaces_and_lists_newest_first(tmp_path):
    store = SqliteShownStore(str(tmp_path / "history.sqlite3"), LOG)
    store.keep(shown("aaa111", "2026-11-01T10:00:00+00:00"))
    store.keep(shown("bbb222", "2026-11-01T11:00:00+00:00", Kind.PRIVATE_PLANE, owner="A Football Club", km=5.0))
    store.keep(shown("bbb222", "2026-11-01T11:00:00+00:00", Kind.PRIVATE_PLANE, owner="A Football Club", km=2.0))
    store.keep(shown("ccc333", "2026-11-01T12:00:00+00:00"))
    assert [(s.hex, s.closest_km, s.owner) for s in store.everything()] == [
        ("ccc333", 3.0, None),
        ("bbb222", 2.0, "A Football Club"),
        ("aaa111", 3.0, None),
    ]


def test_only_old_airline_flights_are_forgotten(tmp_path):
    store = SqliteShownStore(str(tmp_path / "history.sqlite3"), LOG)
    old, new = "2026-01-01T12:00:00+00:00", "2026-11-01T12:00:00+00:00"
    for hex_code, at, kind in [
        ("old-airline", old, Kind.AIRLINE),
        ("new-airline", new, Kind.AIRLINE),
        ("old-police", old, Kind.POLICE),
        ("old-private", old, Kind.PRIVATE_PLANE),
        ("old-heli", old, Kind.PRIVATE_HELICOPTER),
    ]:
        store.keep(shown(hex_code, at, kind))
    store.forget_airlines_before(datetime(2026, 8, 3, 13, tzinfo=BST))
    assert sorted(s.hex for s in store.everything()) == ["new-airline", "old-heli", "old-police", "old-private"]


def test_forgetting_runs_each_time_a_plane_is_kept():
    kept, clock = Kept(), FakeClock(datetime(2026, 11, 1, 12, tzinfo=UTC))
    store = Forgetting(kept, timedelta(days=90), clock)
    store.keep(shown())
    assert kept.forgotten == [datetime(2026, 8, 3, 12, tzinfo=UTC)]
    assert store.everything() == [shown()]


def test_a_broken_store_is_logged_and_reads_as_empty(tmp_path, caplog):
    broken = tmp_path / "history.sqlite3"
    broken.write_text("not a database")
    store = SqliteShownStore(str(broken), LOG)
    store.keep(shown())
    store.forget_airlines_before(datetime(2026, 1, 1, tzinfo=UTC))
    assert store.everything() == []
    assert "could not keep abc123" in caplog.text
    assert "could not forget old flights" in caplog.text
    assert "could not read the history" in caplog.text


def test_a_store_whose_table_cannot_be_made_closes_its_connection(tmp_path, monkeypatch):
    closed = []

    class Refusing:
        def execute(self, *_):
            raise sqlite3.OperationalError("read only")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(sqlite3, "connect", lambda _: Refusing())
    assert SqliteShownStore(str(tmp_path / "h.sqlite3"), LOG).everything() == []
    assert closed == [True]


def test_the_page_has_everything_kept_newest_first(tmp_path):
    store = SqliteShownStore(str(tmp_path / "history.sqlite3"), LOG)
    store.keep(shown("aaa111", "2026-11-01T10:00:00+00:00"))
    store.keep(shown("bbb222", "2026-11-01T11:00:00+00:00", Kind.PRIVATE_PLANE, owner="A Pop Star"))
    page = HistoryPage(store).latest()
    assert [(row["hex"], row["kind"], row["owner"]) for row in page["shown"]] == [
        ("bbb222", "private-plane", "A Pop Star"),
        ("aaa111", "airline", None),
    ]
