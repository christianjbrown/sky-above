"""A web picture of who a notable aircraft belongs to, cut to a square round their face, so
it fills the card's tile with their head in shot however the photo was framed."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from flights_watcher.files import KeptFiles
from flights_watcher.http import BytesHttp
from flights_watcher.lookups import LookupFailed
from flights_watcher.portraits import PortraitLookup


@dataclass(frozen=True)
class Box:
    """A rectangle in a picture, in pixels from its top left corner."""

    left: int
    top: int
    width: int
    height: int

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class Picture:
    """A decoded picture: its pixels, in whatever form the tools that made it use, and its size."""

    pixels: Any
    width: int
    height: int


@dataclass(frozen=True)
class Framing:
    """How much of the picture goes round the face: the square's side as a multiple of the
    face's, and the share of the room left over that goes above the face rather than below,
    so the head sits a little above the middle with the shoulders under it."""

    zoom: float
    headroom: float

    def square(self, width: int, height: int, face: Box | None) -> Box:
        """The square to cut from a picture of this size, round the face when there is one.
        Without a face it is the top of the picture, where a head usually is, centred."""
        side = min(width, height)
        if face is None:
            return Box((width - side) // 2, 0, side, side)
        side = min(round(max(face.width, face.height) * self.zoom), side)
        left = face.left + (face.width - side) / 2
        top = face.top - (side - face.height) * self.headroom
        return Box(_within(left, width - side), _within(top, height - side), side, side)


def _within(value: float, most: int) -> int:
    return int(min(max(value, 0), most))


class FaceFinder(Protocol):
    def faces(self, picture: Picture) -> list[Box]:
        """Where the faces in the picture are."""
        ...


class PictureEditor(Protocol):
    def decode(self, data: bytes) -> Picture | None:
        """The picture in the bytes, or None when they are not a picture it can read."""
        ...

    def square_jpeg(self, picture: Picture, square: Box, side: int, quality: int) -> bytes:
        """The square cut out of the picture, scaled to the side given, as a JPEG."""
        ...


class FaceCrops:
    """Each web picture cut to a square round the largest face in it, kept in a folder the
    receiver serves. A picture that cannot be fetched is a failed lookup, and one that is not
    a picture this can read is shown as it is."""

    def __init__(
        self,
        inner: PortraitLookup,
        http: BytesHttp,
        pictures: PictureEditor,
        faces: FaceFinder,
        framing: Framing,
        files: KeptFiles,
        side: int,
        quality: int,
        logger: logging.Logger,
    ) -> None:
        self._inner = inner
        self._http = http
        self._pictures = pictures
        self._faces = faces
        self._framing = framing
        self._files = files
        self._side = side
        self._quality = quality
        self._logger = logger

    def portrait(self, article: str) -> str | None:
        url = self._inner.portrait(article)
        if url is None:
            return None
        try:
            return self._files.url_for(url, self._square_of(url))
        except UnreadablePicture:
            self._logger.warning("the picture of %s at %s cannot be read, showing it as it is", article, url)
            return url

    def _square_of(self, url: str) -> Callable[[], bytes]:
        def make() -> bytes:
            try:
                data = self._http.get_bytes(url)
            except (OSError, ValueError) as error:
                raise LookupFailed(str(error)) from error
            picture = self._pictures.decode(data)
            if picture is None:
                raise UnreadablePicture(url)
            face = max(self._faces.faces(picture), key=lambda found: found.area, default=None)
            square = self._framing.square(picture.width, picture.height, face)
            return self._pictures.square_jpeg(picture, square, self._side, self._quality)

        return make


class UnreadablePicture(Exception):
    pass
