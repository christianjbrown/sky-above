"""Test doubles shared across the suite."""

from datetime import datetime
from typing import Any
from urllib.error import HTTPError

from flights_watcher.aircraft import Aircraft
from flights_watcher.geo import Location

# The Royal Observatory, Greenwich: a stand-in, never the real home.
HOME = Location(51.4769, 0.0)


class FakeClock:
    def __init__(self, at: datetime = datetime(2026, 11, 1, 12, 0)) -> None:
        self.seconds = 0.0
        self.at = at

    def monotonic(self) -> float:
        return self.seconds

    def now(self) -> datetime:
        return self.at


class FakeHttp:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.requested: list[str] = []

    def get_json(self, url: str) -> Any:
        self.requested.append(url)
        answer = self.responses[url]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def http_error(code: int) -> HTTPError:
    return HTTPError("http://example.test", code, "error", {}, None)


def plane(hex_code: str = "abc123", lat: float = HOME.lat + 0.004, lon: float = HOME.lon, **overrides: Any) -> Aircraft:
    fields: dict[str, Any] = {
        "hex": hex_code,
        "callsign": "BAW86S",
        "registration": "G-EUYM",
        "type_code": "A320",
        "description": "AIRBUS A-320",
        "location": Location(lat, lon),
        "altitude_ft": 4000,
        "on_ground": False,
        "ground_speed_kt": 240.0,
        "track_deg": 270.0,
        "vertical_rate_fpm": -640,
    }
    fields.update(overrides)
    return Aircraft(**fields)


class FakeDevice:
    def __init__(self, running: str | None = "E8C28D3C", idle: bool = True) -> None:
        self.running = running
        self.idle = idle
        self.sent: list[dict[str, Any]] = []
        self.launched: list[str] = []
        self.quits = 0
        self.hidden = False

    def running_app_id(self) -> str | None:
        return self.running

    def is_idle(self) -> bool:
        return self.idle

    def is_hidden(self) -> bool:
        return self.hidden

    def launch(self, app_id: str) -> None:
        self.launched.append(app_id)
        self.running, self.idle, self.hidden = app_id, False, False

    def send(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    def quit(self) -> None:
        self.quits += 1
        self.running, self.idle = "E8C28D3C", True


class RecordingDisplay:
    def __init__(self) -> None:
        self.shown: list[dict[str, Any]] = []
        self.clears = 0

    def show(self, message: dict[str, Any]) -> bool:
        self.shown.append(message)
        return True

    def clear(self) -> None:
        self.clears += 1
