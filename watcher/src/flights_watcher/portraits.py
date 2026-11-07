"""A picture of who a notable aircraft belongs to, for its card."""

import logging
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import quote

from flights_watcher.caching import TtlCache
from flights_watcher.http import JsonHttp
from flights_watcher.lookups import LookupFailed

# Pictures from Wikimedia Commons are free to show. Ones uploaded to a Wikipedia itself are
# mostly logos and crests used under fair use, which is not this display's to borrow.
_FREE_PICTURES = "/wikipedia/commons/"


class PortraitLookup(Protocol):
    def portrait(self, article: str) -> str | None:
        """The web address of a picture of the article's subject, or None when it has none.
        Raises LookupFailed."""
        ...


class NoPortraits:
    def portrait(self, article: str) -> str | None:
        return None


class WikipediaPortraits:
    """The lead picture of a Wikipedia article, which for someone famous is their official
    portrait where they have one, or a recent photo. A name that could be several people
    lands on a disambiguation page, which has none."""

    def __init__(self, base_url: str, http: JsonHttp) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http

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
        source = (page.get("thumbnail") or {}).get("source")
        return source if isinstance(source, str) and _FREE_PICTURES in source else None


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
