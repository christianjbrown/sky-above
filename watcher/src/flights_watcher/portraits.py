"""A picture of who a notable aircraft belongs to, for its card."""

import logging
import pathlib
import re
from collections.abc import Sequence
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import quote

from flights_watcher.caching import TtlCache
from flights_watcher.http import JsonHttp
from flights_watcher.lookups import LookupFailed

# Pictures from Wikimedia Commons are free to show. Ones uploaded to a Wikipedia itself are
# mostly logos and crests used under fair use, which is not this display's to borrow.
_FREE_PICTURES = "/wikipedia/commons/"
# The width in a Commons thumbnail's address: .../A_Pop_Star.jpg/330px-A_Pop_Star.jpg.
_THUMBNAIL_WIDTH = re.compile(r"/\d+px-")


class PortraitLookup(Protocol):
    def portrait(self, article: str) -> str | None:
        """The web address of a picture of the article's subject, or None when it has none.
        Raises LookupFailed."""
        ...


class WikipediaPortraits:
    """The lead picture of a Wikipedia article, which for someone famous is their official
    portrait where they have one, or a recent photo. A name that could be several people
    lands on a disambiguation page, which has none. The picture is asked for at the width
    given, which has to be one Commons serves, or whole when it is no wider than that."""

    def __init__(self, base_url: str, http: JsonHttp, width: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http
        self._width = width

    def portrait(self, article: str) -> str | None:
        url = f"{self._base_url}/page/summary/{quote(article.replace(' ', '_'), safe='')}"
        try:
            page = self._http.get_json(url)
        except HTTPError as error:
            if error.code == 404:
                return None
            raise LookupFailed(str(error)) from error
        except (OSError, ValueError) as error:
            raise LookupFailed(str(error)) from error
        if not isinstance(page, dict) or page.get("type") != "standard":
            return None
        source = self._sized(page.get("thumbnail") or {}, page.get("originalimage") or {})
        return source if isinstance(source, str) and _FREE_PICTURES in source else None

    def _sized(self, thumbnail: Any, original: Any) -> Any:
        source = thumbnail.get("source")
        if not isinstance(source, str):
            return None
        if isinstance(original.get("width"), int) and original["width"] <= self._width and isinstance(original.get("source"), str):
            return original["source"]
        return _THUMBNAIL_WIDTH.sub(f"/{self._width}px-", source)


class LocalPortraits:
    """Pictures kept on the Pi, for owners whose only picture online is a logo or crest
    that may be shown at home but not handed out. Each is named after the owner, lower
    case with hyphens between the words: leicester-city-football-club.png."""

    _KINDS = (".jpg", ".jpeg", ".png", ".webp", ".svg")

    def __init__(self, folder: pathlib.Path, url_prefix: str) -> None:
        self._folder = folder
        self._url_prefix = url_prefix

    def portrait(self, article: str) -> str | None:
        name = file_name(article)
        return next((self._url_prefix + name + kind for kind in self._KINDS if (self._folder / (name + kind)).is_file()), None)


def file_name(owner: str) -> str:
    """The name an owner's picture is kept under: "A Football Club" is a-football-club."""
    return re.sub(r"[^a-z0-9]+", "-", owner.lower()).strip("-")


class FirstPortrait:
    """The first of several places that has a picture."""

    def __init__(self, places: Sequence[PortraitLookup]) -> None:
        self._places = places

    def portrait(self, article: str) -> str | None:
        return next((found for place in self._places if (found := place.portrait(article))), None)


class CachedPortraits:
    """Each article asked about once in a while. A failed lookup counts as no picture for
    the cache's shorter time, so a service that is down is not asked on every look."""

    def __init__(self, inner: PortraitLookup, cache: TtlCache[str | None], logger: logging.Logger) -> None:
        self._inner = inner
        self._cache = cache
        self._logger = logger

    def portrait(self, article: str) -> str | None:
        found, value = self._cache.get(article)
        if found:
            return value
        try:
            value = self._inner.portrait(article)
        except LookupFailed as error:
            self._logger.warning("portrait lookup for %s failed: %s", article, error)
            value = None
        self._cache.put(article, value)
        return value
