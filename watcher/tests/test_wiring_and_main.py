import logging
import threading
from datetime import UTC

import pytest
from test_config_and_wiring import FULL_ENV

from fakes import FakeClock
from flights_watcher import __main__ as entry
from flights_watcher import wiring
from flights_watcher.chime import MutedLaunchDevice
from flights_watcher.clock import SystemClock
from flights_watcher.config import Settings
from flights_watcher.http import UrllibJsonHttp
from flights_watcher.live import LatestCard, LiveServer
from flights_watcher.lookups import NoPhotos
from flights_watcher.rare import RareKinds
from flights_watcher.speech import QuietVoice, Silence
from flights_watcher.standby import FollowedStandby, NothingOnStandby
from flights_watcher.status import WatchStatus

LOGGER = logging.getLogger("test")


def settings(tmp_path, **changes: str) -> Settings:
    env = {**FULL_ENV, "STATE_DIR": str(tmp_path), "SPEECH_DIR": str(tmp_path / "speech"), "LIVE_PORT": "0", **changes}
    return Settings.from_env(env)


def test_with_everything_switched_on_every_part_is_built(tmp_path):
    full = settings(tmp_path, AEROAPI_KEY="test-key", CAST_APP_ID="APP")
    app = wiring.build(full, FakeClock(), LOGGER)
    found = wiring.lookups(full, UrllibJsonHttp("test", 1), FakeClock(), LOGGER)
    voice = wiring.voices(full, FakeClock(), RareKinds(()), LOGGER)
    assert app.live_server is not None
    assert found.operator_names is not None
    assert not isinstance(found.photos, NoPhotos)
    assert found.known_routes is not found.routes
    assert isinstance(voice.planes, QuietVoice) and isinstance(voice.followed, QuietVoice)
    assert isinstance(wiring.followed_standby(full, found, voice, FakeClock(), LOGGER), FollowedStandby)


def test_with_everything_switched_off_the_watcher_still_runs_on_its_own(tmp_path, caplog):
    bare = settings(
        tmp_path, ROUTE_API_URL="", PHOTO_API_URL="", SPEECH_SERVER="", LIVE_PORT="", FOLLOWED_FILE="", HOME_COUNTRY="", CAST_APP_ID=""
    )
    with caplog.at_level(logging.INFO, logger="test"):
        app = wiring.build(bare, FakeClock(), LOGGER)
    found = wiring.lookups(bare, UrllibJsonHttp("test", 1), FakeClock(), LOGGER)
    voice = wiring.voices(bare, FakeClock(), RareKinds(()), LOGGER)
    assert app.live_server is None
    assert found.operator_names is None and isinstance(found.photos, NoPhotos)
    assert isinstance(voice.planes, Silence) and isinstance(voice.followed, Silence)
    assert isinstance(wiring.followed_standby(bare, found, voice, FakeClock(), LOGGER), NothingOnStandby)
    assert "planes are logged rather than cast" in caplog.text
    assert "going by the nearest airport: GB" in caplog.text


def test_followed_flights_need_aeroapi_as_well_as_a_list(tmp_path):
    adsbdb_only = settings(tmp_path)
    found = wiring.lookups(adsbdb_only, UrllibJsonHttp("test", 1), FakeClock(), LOGGER)
    assert found.known_routes is found.routes
    voice = wiring.voices(adsbdb_only, FakeClock(), RareKinds(()), LOGGER)
    assert isinstance(wiring.followed_standby(adsbdb_only, found, voice, FakeClock(), LOGGER), NothingOnStandby)


@pytest.mark.parametrize(("mute", "muted_launch"), [("true", True), ("false", False)])
def test_the_hub_is_muted_through_its_chime_only_when_asked(tmp_path, monkeypatch, mute, muted_launch):
    wrapped = []
    monkeypatch.setattr(wiring, "CoolingOffDevice", lambda hub, *_: wrapped.append(hub) or hub)
    wiring.display_for(settings(tmp_path, CAST_APP_ID="APP", MUTE_CHIME=mute, LIVE_PORT=""), WatchStatus(FakeClock()), FakeClock(), LOGGER)
    assert isinstance(wrapped[0], MutedLaunchDevice) is muted_launch


def test_main_runs_until_told_to_stop_and_closes_the_live_page(tmp_path, monkeypatch):
    env = {**FULL_ENV, "STATE_DIR": str(tmp_path), "SPEECH_DIR": str(tmp_path / "speech"), "LIVE_PORT": "0", "SPEECH_SERVER": ""}
    started: list[LiveServer] = []
    real_build = wiring.build

    def build(*args):
        app = real_build(*args)
        started.append(app.live_server)
        return app

    monkeypatch.setattr(entry, "build", build)
    monkeypatch.setattr(entry.signal, "signal", lambda *_: None)
    stop = threading.Event()
    stop.set()
    entry.main(env, stop)
    assert started[0]._server is None


def test_main_without_a_live_page_just_runs(tmp_path, monkeypatch):
    env = {**FULL_ENV, "STATE_DIR": str(tmp_path), "LIVE_PORT": "", "SPEECH_SERVER": ""}
    monkeypatch.setattr(entry.signal, "signal", lambda *_: None)
    stop = threading.Event()
    stop.set()
    entry.main(env, stop)


def test_main_stops_on_sigterm_or_sigint(tmp_path, monkeypatch):
    handlers = {}
    monkeypatch.setattr(entry.signal, "signal", lambda signum, handler: handlers.update({signum: handler}))
    stop = threading.Event()
    stop.set()
    entry.main({**FULL_ENV, "STATE_DIR": str(tmp_path), "LIVE_PORT": "", "SPEECH_SERVER": ""}, stop)
    for signum in (entry.signal.SIGTERM, entry.signal.SIGINT):
        stop.clear()
        handlers[signum](signum, None)
        assert stop.is_set()


def test_the_system_clock_tells_the_time_in_its_zone():
    clock = SystemClock(UTC)
    assert clock.now().tzinfo is UTC
    assert clock.monotonic() <= clock.monotonic()


def test_json_is_fetched_over_http_and_only_http():
    card = LatestCard()
    card.show({"type": "planes"})
    server = LiveServer({"/planes.json": card}, "127.0.0.1", 0, LOGGER)
    port = server.start()
    try:
        http = UrllibJsonHttp("test", 2, {"X-Test": "1"})
        assert http.get_json(f"http://127.0.0.1:{port}/planes.json") == {"type": "planes"}
        with pytest.raises(ValueError, match="not a web address"):
            http.get_json("file:///etc/passwd")
    finally:
        server.stop()
