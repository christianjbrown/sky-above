import logging
import sqlite3
from datetime import UTC, datetime, timedelta, timezone

from fakes import FakeClock
from flights_watcher.history import HistoryPage, Shown, ShownHistory, SqliteShownStore

LOG = logging.getLogger("test")
BST = timezone(timedelta(hours=1))


def card(hex_code="abc123", km=3.0, ft=4000, **extra):
    return {"hex": hex_code, "distanceKm": km, "altitudeFt": ft, **extra}


def planes(*cards):
    return {"type": "planes", "planes": list(cards)}


def shown(hex_code="abc123", at="2026-11-01T12:00:00+00:00", owner=None, km=3.0):
    return Shown(hex_code, at, None, None, None, None, None, None, None, None, None, owner, None, None, km, 4000)


class Kept:
    def __init__(self):
        self.kept = []

    def keep(self, s):
        self.kept.append(s)


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
        owner="A Pop Star",
        ownerCategory="Don't you know who I am?",
        emergency={"label": "General emergency"},
    )
    assert recorder.show(planes(full, card("second"))) is False
    assert kept.kept == [
        Shown(
            "abc123",
            "2026-07-01T12:00:00+00:00",
            "EZY12AB",
            "U21234",
            "G-EZAB",
            "Airbus A320neo",
            "A20N",
            "easyJet",
            None,
            "Alicante (ALC)",
            "London Stansted (STN)",
            "A Pop Star",
            "Don't you know who I am?",
            "General emergency",
            3.0,
            4000,
        )
    ]


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


def test_the_store_keeps_replaces_and_lists_newest_first_with_famous_ones_apart(tmp_path):
    store = SqliteShownStore(str(tmp_path / "history.sqlite3"), LOG)
    store.keep(shown("aaa111", "2026-11-01T10:00:00+00:00"))
    store.keep(shown("bbb222", "2026-11-01T11:00:00+00:00", owner="A Football Club", km=5.0))
    store.keep(shown("bbb222", "2026-11-01T11:00:00+00:00", owner="A Football Club", km=2.0))
    store.keep(shown("ccc333", "2026-11-01T12:00:00+00:00"))
    assert [(s.hex, s.closest_km) for s in store.recent(10)] == [("ccc333", 3.0), ("bbb222", 2.0), ("aaa111", 3.0)]
    assert [s.hex for s in store.recent(1)] == ["ccc333"]
    assert [s.owner for s in store.famous(10)] == ["A Football Club"]


def test_a_broken_store_is_logged_and_reads_as_empty(tmp_path, caplog):
    broken = tmp_path / "history.sqlite3"
    broken.write_text("not a database")
    store = SqliteShownStore(str(broken), LOG)
    store.keep(shown())
    assert store.recent(10) == []
    assert "could not keep abc123" in caplog.text
    assert "could not read the history" in caplog.text


def test_a_store_whose_table_cannot_be_made_closes_its_connection(tmp_path, monkeypatch):
    closed = []

    class Refusing:
        def execute(self, *_):
            raise sqlite3.OperationalError("read only")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(sqlite3, "connect", lambda _: Refusing())
    assert SqliteShownStore(str(tmp_path / "h.sqlite3"), LOG).famous(1) == []
    assert closed == [True]


def test_the_page_lists_the_latest_and_the_latest_famous(tmp_path):
    store = SqliteShownStore(str(tmp_path / "history.sqlite3"), LOG)
    store.keep(shown("aaa111", datetime(2026, 11, 1, 10, tzinfo=UTC).isoformat()))
    store.keep(shown("bbb222", datetime(2026, 11, 1, 11, tzinfo=UTC).isoformat(), owner="A Pop Star"))
    page = HistoryPage(store, recent=1, famous=5).latest()
    assert [row["hex"] for row in page["recent"]] == ["bbb222"]
    assert page["famous"][0]["owner"] == "A Pop Star"
    assert page["famous"][0]["shown_at"] == "2026-11-01T11:00:00+00:00"
