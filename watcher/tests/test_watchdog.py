import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest

from fakes import FakeClock
from flights_watcher import watchdog
from flights_watcher.watchdog import (
    HearsNothing,
    HttpStatus,
    KeepsFailing,
    LoggedAlerts,
    PostedAlerts,
    Stopped,
    Watchdog,
    WatchdogSettings,
)

LOG = logging.getLogger("test")
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def ago(minutes: float) -> str:
    return (NOW - timedelta(minutes=minutes)).isoformat()


HEALTHY = {"lastLook": ago(0), "failingSince": None, "failure": None, "aircraft": 12, "aircraftHeardAt": ago(0), "planesToday": 3}


def test_a_watcher_that_does_not_answer_or_has_not_looked_lately_has_stopped():
    stopped = Stopped(timedelta(minutes=3))
    assert stopped.problem(None, NOW) == "The watcher is not answering."
    assert stopped.problem({**HEALTHY, "lastLook": ago(4)}, NOW) == "The watcher has stopped looking at the sky."
    assert stopped.problem({**HEALTHY, "lastLook": None}, NOW) == "The watcher has stopped looking at the sky."
    assert stopped.problem(HEALTHY, NOW) is None


def test_a_watcher_failing_every_look_for_a_while_says_why():
    failing = KeepsFailing(timedelta(minutes=5))
    assert failing.problem({**HEALTHY, "failingSince": ago(7), "failure": "ConnectionError: no Hub"}, NOW) == (
        "The watcher has been failing for 7 minutes: ConnectionError: no Hub"
    )
    assert failing.problem({**HEALTHY, "failingSince": ago(2), "failure": "x"}, NOW) is None
    assert failing.problem(HEALTHY, NOW) is None
    assert failing.problem(None, NOW) is None


def test_an_antenna_that_has_heard_nothing_for_an_hour_is_reported_once_the_watcher_is_looking():
    deaf = HearsNothing(timedelta(minutes=60))
    assert deaf.problem({**HEALTHY, "aircraftHeardAt": ago(61)}, NOW) == "The antenna has not heard an aircraft for over 60 minutes."
    assert deaf.problem({**HEALTHY, "aircraftHeardAt": None}, NOW) is not None
    assert deaf.problem(HEALTHY, NOW) is None
    assert deaf.problem({**HEALTHY, "lastLook": None}, NOW) is None
    assert deaf.problem(None, NOW) is None


class Statuses:
    def __init__(self, *statuses) -> None:
        self._statuses = list(statuses)

    def status(self):
        return self._statuses.pop(0)


class Sent:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def send(self, text: str) -> None:
        self.texts.append(text)


def test_a_problem_is_alerted_once_when_it_starts_and_once_when_it_clears():
    sent = Sent()
    dog = Watchdog(Statuses(None, None, HEALTHY), [Stopped(timedelta(minutes=3))], sent, FakeClock(NOW))
    dog.check()
    dog.check()
    dog.check()
    assert sent.texts == ["The watcher is not answering.", "Working again: The watcher is not answering."]


class Handler(BaseHTTPRequestHandler):
    posted: ClassVar[list[tuple[str, str]]] = []

    def do_GET(self) -> None:
        body = json.dumps(HEALTHY if self.path == "/status.json" else [1]).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        Handler.posted.append((self.headers["Title"], self.rfile.read(int(self.headers["Content-Length"])).decode()))
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args) -> None:
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_the_status_is_read_over_http_and_anything_else_is_no_answer(server):
    assert HttpStatus(f"{server}/status.json", 2).status() == HEALTHY
    assert HttpStatus(f"{server}/list.json", 2).status() is None
    assert HttpStatus("http://127.0.0.1:1/status.json", 2).status() is None


def test_alerts_are_posted_as_plain_text_or_logged_when_that_fails(server, caplog):
    Handler.posted.clear()
    PostedAlerts(f"{server}/topic", 2, LOG).send("The watcher is not answering.")
    assert Handler.posted == [("Sky Above", "The watcher is not answering.")]
    with caplog.at_level(logging.WARNING, logger="test"):
        PostedAlerts("http://127.0.0.1:1/topic", 2, LOG).send("lost")
        LoggedAlerts(LOG).send("only logged")
    assert "could not send the alert 'lost'" in caplog.text
    assert "alert: only logged" in caplog.text


def test_settings_default_to_the_local_watcher_and_logged_alerts():
    assert WatchdogSettings.from_env({}) == WatchdogSettings("http://localhost:8091/status.json", None)
    assert (
        WatchdogSettings.from_env({"STATUS_URL": "http://x/s", "ALERT_URL": " https://ntfy.example/t "}).alert_url
        == "https://ntfy.example/t"
    )


def test_main_checks_until_told_to_stop(monkeypatch):
    checks = []
    monkeypatch.setattr(watchdog, "CHECK_EVERY_SECONDS", 0)
    monkeypatch.setattr(watchdog.signal, "signal", lambda *_: None)
    monkeypatch.setattr(watchdog.Watchdog, "check", lambda _self: checks.append(1) or stop.set())
    stop = threading.Event()
    watchdog.main({"ALERT_URL": "http://127.0.0.1:1/topic"}, stop)
    assert checks == [1]
    assert isinstance(watchdog.build(WatchdogSettings("http://x", None), LOG), Watchdog)


def test_main_stops_on_sigterm_or_sigint(monkeypatch):
    handlers = {}
    monkeypatch.setattr(watchdog.signal, "signal", lambda signum, handler: handlers.update({signum: handler}))
    stop = threading.Event()
    stop.set()
    watchdog.main({}, stop)
    for signum in (watchdog.signal.SIGTERM, watchdog.signal.SIGINT):
        stop.clear()
        handlers[signum](signum, None)
        assert stop.is_set()


def test_an_alert_address_that_is_not_a_web_address_is_refused():
    with pytest.raises(ValueError, match="not a web address"):
        WatchdogSettings.from_env({"ALERT_URL": "file:///etc/passwd"})
