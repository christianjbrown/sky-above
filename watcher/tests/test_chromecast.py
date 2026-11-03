import logging
from types import SimpleNamespace

import pytest

from flights_watcher import chromecast
from flights_watcher.chromecast import ListedChromecasts, PyChromecastDevice, planes_channel

LOGGER = logging.getLogger("test")


class FakeChannel:
    def __init__(self) -> None:
        self.hidden = False
        self.sent: list[dict] = []

    def send_message(self, data: dict) -> None:
        self.sent.append(data)


class FakeCast:
    def __init__(self, fail: str | None = None) -> None:
        self.name, self.uri = "Display", "192.0.2.1:8009"
        self.app_id: str | None = "E8C28D3C"
        self.is_idle = False
        self.status = SimpleNamespace(volume_muted=True)
        self.calls: list[tuple] = []
        self.handlers: list = []
        self._fail = fail

    def wait(self, timeout=None) -> None:
        self.calls.append(("wait", timeout))

    def register_handler(self, handler) -> None:
        self.handlers.append(handler)

    def start_app(self, app_id, force_launch=False, timeout=0.0) -> None:
        if self._fail == "start_app":
            raise TimeoutError("no answer")
        self.calls.append(("start_app", app_id, timeout))

    def quit_app(self, timeout=0.0) -> None:
        self.calls.append(("quit_app", timeout))

    def set_volume_muted(self, muted, timeout=0.0) -> None:
        self.calls.append(("set_volume_muted", muted, timeout))

    def disconnect(self, timeout=None) -> None:
        if self._fail == "disconnect":
            raise OSError("already gone")
        self.calls.append(("disconnect", timeout))


class FakeBrowser:
    def __init__(self, fail: bool = False) -> None:
        self.stopped = False
        self._fail = fail

    def stop_discovery(self) -> None:
        if self._fail:
            raise RuntimeError("zeroconf closed")
        self.stopped = True


class FakeDiscovery:
    def __init__(self, *finds: tuple[list, FakeBrowser]) -> None:
        self._finds = list(finds)
        self.looks = 0

    def find(self):
        self.looks += 1
        return self._finds.pop(0)


def device(discovery: FakeDiscovery, channel: FakeChannel | None = None) -> PyChromecastDevice:
    return PyChromecastDevice(discovery, lambda: channel or FakeChannel(), 5.0, LOGGER)


def test_the_device_is_found_once_and_its_state_read_through_the_same_connection():
    cast, channel = FakeCast(), FakeChannel()
    discovery = FakeDiscovery(([cast], FakeBrowser()))
    hub = device(discovery, channel)
    assert hub.running_app_id() == "E8C28D3C"
    assert hub.is_idle() is False
    assert hub.is_muted() is True
    assert discovery.looks == 1
    assert cast.handlers == [channel]
    assert cast.calls[0] == ("wait", 5.0)


def test_commands_go_to_the_device_and_the_card_channel():
    cast, channel = FakeCast(), FakeChannel()
    hub = device(FakeDiscovery(([cast], FakeBrowser())), channel)
    channel.hidden = True
    hub.launch("APP")
    assert channel.hidden is False
    assert hub.is_hidden() is False
    hub.send({"type": "planes"})
    hub.set_muted(False)
    hub.quit()
    assert channel.sent == [{"type": "planes"}]
    assert ("start_app", "APP", 5.0) in cast.calls
    assert ("set_volume_muted", False, 5.0) in cast.calls
    assert ("quit_app", 5.0) in cast.calls


def test_a_device_that_is_not_found_is_looked_for_again_next_time():
    browser, cast = FakeBrowser(), FakeCast()
    discovery = FakeDiscovery(([], browser), ([cast], FakeBrowser()))
    hub = device(discovery)
    with pytest.raises(ConnectionError):
        hub.is_idle()
    assert browser.stopped
    assert hub.running_app_id() == "E8C28D3C"
    assert discovery.looks == 2


def test_a_failure_drops_the_connection_so_the_next_call_reconnects():
    first, second = FakeCast(fail="start_app"), FakeCast()
    browser = FakeBrowser()
    discovery = FakeDiscovery(([first], browser), ([second], FakeBrowser()))
    hub = device(discovery)
    with pytest.raises(TimeoutError):
        hub.launch("APP")
    assert ("disconnect", 5.0) in first.calls
    assert browser.stopped
    hub.launch("APP")
    assert ("start_app", "APP", 5.0) in second.calls


def test_a_failed_disconnect_is_logged_and_does_not_hide_the_first_error(caplog):
    cast = FakeCast(fail="start_app")
    discovery = FakeDiscovery(([cast], FakeBrowser(fail=True)))
    hub = device(discovery)

    def gone(timeout=None):  # noqa: ARG001 - stands in for disconnect
        raise OSError("already gone")

    cast.disconnect = gone
    with caplog.at_level(logging.DEBUG, logger="test"), pytest.raises(TimeoutError):
        hub.launch("APP")
    assert "disconnecting from the display failed" in caplog.text
    assert "stopping discovery failed" in caplog.text


def test_the_card_channel_notices_when_the_hub_covers_it():
    channel = planes_channel("APP")()
    assert channel.hidden is False
    assert channel.receive_message(None, {"type": "other"}) is True
    assert channel.hidden is False
    channel.receive_message(None, {"type": "hidden"})
    assert channel.hidden is True


def test_listed_chromecasts_asks_pychromecast_for_the_device_by_name(monkeypatch):
    asked = {}

    def listed(friendly_names, discovery_timeout):
        asked.update(names=friendly_names, timeout=discovery_timeout)
        return (["cast"], "browser")

    monkeypatch.setattr(chromecast.pychromecast, "get_listed_chromecasts", listed)
    assert ListedChromecasts("Display", 3.0).find() == (["cast"], "browser")
    assert asked == {"names": ["Display"], "timeout": 3.0}


def test_a_failed_search_leaves_nothing_to_stop():
    class Failing:
        def find(self):
            raise OSError("no network")

    hub = PyChromecastDevice(Failing(), FakeChannel, 5.0, LOGGER)
    with pytest.raises(OSError, match="no network"):
        hub.is_idle()
