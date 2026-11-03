"""The Nest Hub itself, reached through pychromecast."""

import logging
from collections.abc import Callable
from typing import Any, Protocol

import pychromecast
from pychromecast.controllers import BaseController

# The custom message channel between this service and receiver/app.js. Both
# ends hard-code it, and tests/test_namespace.py pins them to the same value.
NAMESPACE = "urn:x-cast:sky-above"


class Channel(Protocol):
    """The card's own message channel on a connected device."""

    hidden: bool

    def send_message(self, data: dict[str, Any]) -> None: ...


class _PlanesChannel(BaseController):
    def __init__(self, app_id: str) -> None:
        super().__init__(NAMESPACE, app_id)
        # Set when the card says the Hub has covered it, until it is relaunched.
        self.hidden = False

    def receive_message(self, _message: Any, data: dict[str, Any]) -> bool:
        if data.get("type") == "hidden":
            self.hidden = True
        return True


def planes_channel(app_id: str) -> Callable[[], Channel]:
    """A fresh channel for each connection, as pychromecast registers it with one."""
    return lambda: _PlanesChannel(app_id)


class Cast(Protocol):
    """The parts of a pychromecast.Chromecast used here."""

    name: str | None
    uri: str
    app_id: str | None
    is_idle: bool
    status: Any

    def wait(self, timeout: float | None = None) -> None: ...
    def register_handler(self, handler: Any) -> None: ...
    def start_app(self, app_id: str, force_launch: bool = False, timeout: float = ...) -> None: ...
    def quit_app(self, timeout: float = ...) -> None: ...
    def set_volume_muted(self, muted: bool, timeout: float = ...) -> None: ...
    def disconnect(self, timeout: float | None = None) -> None: ...


class Browser(Protocol):
    def stop_discovery(self) -> None: ...


class Discovery(Protocol):
    def find(self) -> tuple[list[Cast], Browser]:
        """The devices found, and the browser that has to keep running while they are used."""
        ...


class ListedChromecasts:
    """Looks for the Cast device with this name on the local network."""

    def __init__(self, friendly_name: str, timeout_seconds: float) -> None:
        self._friendly_name = friendly_name
        self._timeout_seconds = timeout_seconds

    def find(self) -> tuple[list[Cast], Browser]:
        casts, browser = pychromecast.get_listed_chromecasts(friendly_names=[self._friendly_name], discovery_timeout=self._timeout_seconds)
        found: list[Any] = list(casts)
        return found, browser


class PyChromecastDevice:
    """Finds the device on first use, and again after any failure."""

    def __init__(self, discovery: Discovery, channel_for: Callable[[], Channel], timeout_seconds: float, logger: logging.Logger) -> None:
        self._discovery = discovery
        self._channel_for = channel_for
        self._timeout_seconds = timeout_seconds
        self._logger = logger
        self._connected: tuple[Cast, Channel] | None = None
        self._browser: Browser | None = None

    def running_app_id(self) -> str | None:
        return self._call(lambda cast, _channel: cast.app_id)

    def is_idle(self) -> bool:
        return self._call(lambda cast, _channel: cast.is_idle)

    def launch(self, app_id: str) -> None:
        def start(cast: Cast, channel: Channel) -> None:
            cast.start_app(app_id, timeout=self._timeout_seconds)
            channel.hidden = False

        self._call(start)

    def is_hidden(self) -> bool:
        return self._call(lambda _cast, channel: channel.hidden)

    def send(self, payload: dict[str, Any]) -> None:
        self._call(lambda _cast, channel: channel.send_message(payload))

    def quit(self) -> None:
        self._call(lambda cast, _channel: cast.quit_app(timeout=self._timeout_seconds))

    def is_muted(self) -> bool:
        return self._call(lambda cast, _channel: bool(cast.status.volume_muted))

    def set_muted(self, muted: bool) -> None:
        self._call(lambda cast, _channel: cast.set_volume_muted(muted, timeout=self._timeout_seconds))

    def _call[R](self, action: Callable[[Cast, Channel], R]) -> R:
        try:
            return action(*self._connect())
        except Exception:
            self._disconnect()
            raise

    def _connect(self) -> tuple[Cast, Channel]:
        if self._connected is not None:
            return self._connected
        # Discovery has to keep running while connected: the connection looks
        # the Hub up through it, and fails with a timeout once it is stopped.
        casts, self._browser = self._discovery.find()
        if not casts:
            raise ConnectionError("the Cast device was not found")
        cast = casts[0]
        cast.wait(timeout=self._timeout_seconds)
        channel = self._channel_for()
        cast.register_handler(channel)
        self._logger.info("connected to %s at %s", cast.name, cast.uri)
        self._connected = cast, channel
        return self._connected

    def _disconnect(self) -> None:
        if self._connected is not None:
            try:
                self._connected[0].disconnect(timeout=self._timeout_seconds)
            except Exception as error:
                self._logger.debug("disconnecting from the display failed: %s", error)
        if self._browser is not None:
            try:
                self._browser.stop_discovery()
            except Exception as error:
                self._logger.debug("stopping discovery failed: %s", error)
        self._connected, self._browser = None, None
