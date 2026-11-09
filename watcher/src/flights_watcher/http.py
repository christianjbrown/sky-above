"""Fetching JSON and text over HTTP."""

import json
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.request import Request, urlopen


class JsonHttp(Protocol):
    def get_json(self, url: str) -> Any:
        """Return the decoded body. Raises OSError (HTTPError included) or ValueError."""
        ...


class UrllibJsonHttp:
    def __init__(self, user_agent: str, timeout_seconds: float, headers: Mapping[str, str] | None = None) -> None:
        self._user_agent = user_agent
        self._timeout_seconds = timeout_seconds
        self._headers = dict(headers or {})

    def get_json(self, url: str) -> Any:
        headers = {"User-Agent": self._user_agent, "Accept": "application/json", **self._headers}
        with _opened(url, headers, self._timeout_seconds) as response:
            return json.load(response)


class TextHttp(Protocol):
    def get_text(self, url: str) -> str:
        """Return the body as text. Raises OSError (HTTPError included) or ValueError."""
        ...


class UrllibTextHttp:
    def __init__(self, user_agent: str, timeout_seconds: float) -> None:
        self._user_agent = user_agent
        self._timeout_seconds = timeout_seconds

    def get_text(self, url: str) -> str:
        with _opened(url, {"User-Agent": self._user_agent}, self._timeout_seconds) as response:
            body: bytes = response.read()
            return body.decode("utf-8")


class BytesHttp(Protocol):
    def get_bytes(self, url: str) -> bytes:
        """Return the body as it is. Raises OSError (HTTPError included) or ValueError."""
        ...


class UrllibBytesHttp:
    def __init__(self, user_agent: str, timeout_seconds: float) -> None:
        self._user_agent = user_agent
        self._timeout_seconds = timeout_seconds

    def get_bytes(self, url: str) -> bytes:
        with _opened(url, {"User-Agent": self._user_agent}, self._timeout_seconds) as response:
            body: bytes = response.read()
            return body


def _opened(url: str, headers: Mapping[str, str], timeout_seconds: float) -> Any:
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"not a web address: {url}")
    request = Request(url, headers=dict(headers))  # noqa: S310 - the scheme is checked above
    return urlopen(request, timeout=timeout_seconds)  # noqa: S310
