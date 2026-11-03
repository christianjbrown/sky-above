"""Fetching JSON over HTTP."""

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
        if not url.startswith(("https://", "http://")):
            raise ValueError(f"not a web address: {url}")
        headers = {"User-Agent": self._user_agent, "Accept": "application/json", **self._headers}
        request = Request(url, headers=headers)  # noqa: S310 - the scheme is checked above
        with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
            return json.load(response)
