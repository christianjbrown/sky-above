"""Files made once and kept in a folder the receiver serves."""

import hashlib
import pathlib
from collections.abc import Callable

# Enough of the hash to tell files apart, short enough to read in a log.
_NAME_LENGTH = 20
_PARTIAL = ".part"


class KeptFiles:
    """A folder of files the receiver serves, each named by a hash of what it was made from,
    so the same thing is not made twice. Only the newest few are kept. A file is written
    whole or not at all, so the receiver never serves half of one."""

    def __init__(self, directory: pathlib.Path, url_prefix: str, keep: int, kind: str) -> None:
        self._directory = directory
        self._url_prefix = url_prefix
        self._keep = keep
        self._kind = kind

    def url_for(self, source: str, make: Callable[[], bytes]) -> str:
        """The address of the file made from the source, making it if it is not there yet."""
        name = hashlib.sha256(source.encode()).hexdigest()[:_NAME_LENGTH] + self._kind
        path = self._directory / name
        if path.exists():
            path.touch()
        else:
            partial = path.with_suffix(_PARTIAL)
            partial.write_bytes(make())
            partial.replace(path)
            self._prune()
        return self._url_prefix + name

    def _prune(self) -> None:
        kept = sorted(self._directory.glob("*" + self._kind), key=lambda file: file.stat().st_mtime, reverse=True)
        for old in kept[self._keep :]:
            old.unlink(missing_ok=True)
