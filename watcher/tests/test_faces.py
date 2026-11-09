import logging
import pathlib

import pytest

from flights_watcher.faces import Box, FaceCrops, Framing, Picture, UnreadablePicture
from flights_watcher.files import KeptFiles
from flights_watcher.lookups import LookupFailed
from flights_watcher.opencv import YUNET_MODEL, OpenCvPictures, YuNetFaces

# A public domain photograph, Alexander Gardner's of Abraham Lincoln in 1863, small.
PORTRAIT = pathlib.Path(__file__).parent / "pictures" / "lincoln-1863.jpg"
PICTURE = "https://upload.example/wikipedia/commons/thumb/a/ab/A_Pop_Star.jpg/960px-A_Pop_Star.jpg"
FRAMING = Framing(zoom=2.4, headroom=0.4)
LOG = logging.getLogger("test")


def test_the_square_sits_round_the_face_with_more_room_below_it_than_above():
    square = FRAMING.square(960, 1200, Box(400, 300, 100, 100))
    assert square == Box(330, 244, 240, 240)
    assert square.top < 300 and square.top + square.height > 400
    assert (300 - square.top) == pytest.approx((240 - 100) * 0.4, abs=1)


def test_the_square_stays_inside_the_picture_and_no_bigger_than_its_shorter_side():
    assert FRAMING.square(300, 500, Box(0, 0, 100, 100)) == Box(0, 0, 240, 240)
    assert FRAMING.square(300, 500, Box(250, 450, 50, 50)) == Box(180, 380, 120, 120)
    assert FRAMING.square(300, 500, Box(50, 100, 200, 250)) == Box(0, 80, 300, 300)
    assert FRAMING.square(500, 300, Box(0, 0, 400, 300)) == Box(50, 0, 300, 300)


def test_without_a_face_the_square_is_the_top_of_the_picture_centred():
    assert FRAMING.square(400, 1000, None) == Box(0, 0, 400, 400)
    assert FRAMING.square(1000, 400, None) == Box(300, 0, 400, 400)


def test_opencv_finds_the_face_in_a_photo_and_none_in_a_blank_one():
    pictures, faces = OpenCvPictures(), YuNetFaces(YUNET_MODEL, 0.6)
    photo = pictures.decode(PORTRAIT.read_bytes())
    assert photo and (photo.width, photo.height) == (120, 148)
    found = faces.faces(photo)
    assert len(found) == 1
    assert 20 < found[0].left < 50 and 10 < found[0].top < 40 and 30 < found[0].width < 60
    blank = pictures.decode(pictures.square_jpeg(photo, Box(0, 120, 20, 20), 64, 85))
    assert blank and faces.faces(blank) == []
    assert pictures.decode(b"not a picture") is None
    square = pictures.decode(pictures.square_jpeg(photo, FRAMING.square(photo.width, photo.height, found[0]), 32, 85))
    assert square and (square.width, square.height) == (32, 32)


class FixedFaces:
    def __init__(self, boxes):
        self.boxes = boxes
        self.seen = []

    def faces(self, picture):
        self.seen.append(picture)
        return self.boxes


class StubPictures:
    def __init__(self, readable=True):
        self.readable = readable
        self.squares = []

    def decode(self, data):
        return Picture(data, 800, 1000) if self.readable else None

    def square_jpeg(self, picture, square, side, quality):
        self.squares.append((square, side, quality))
        return b"jpeg of " + picture.pixels


class BytesByUrl:
    def __init__(self, answers):
        self.answers = answers
        self.fetched = []

    def get_bytes(self, url):
        self.fetched.append(url)
        answer = self.answers[url]
        if isinstance(answer, BaseException):
            raise answer
        return answer


class Pictured:
    def __init__(self, urls):
        self.urls = urls

    def portrait(self, article):
        return self.urls.get(article)


def crops(tmp_path, pictures, faces, http, keep=5):
    files = KeptFiles(tmp_path, "faces/", keep, ".jpg")
    return FaceCrops(Pictured({"A Pop Star": PICTURE}), http, pictures, faces, FRAMING, files, 320, 85, LOG)


def test_the_largest_face_is_framed_and_the_square_kept_for_next_time(tmp_path):
    pictures = StubPictures()
    faces = FixedFaces([Box(10, 10, 50, 50), Box(300, 200, 200, 200)])
    http = BytesByUrl({PICTURE: b"photo"})
    lookup = crops(tmp_path, pictures, faces, http)
    url = lookup.portrait("A Pop Star")
    assert url and url.startswith("faces/") and url.endswith(".jpg")
    assert (tmp_path / url.removeprefix("faces/")).read_bytes() == b"jpeg of photo"
    assert pictures.squares == [(Box(160, 88, 480, 480), 320, 85)]
    assert lookup.portrait("A Pop Star") == url
    assert http.fetched == [PICTURE]
    assert lookup.portrait("Nobody") is None


def test_a_picture_that_cannot_be_fetched_is_a_failed_lookup_and_an_unreadable_one_is_shown_as_it_is(tmp_path, caplog):
    for error in (OSError("offline"), ValueError("not a web address")):
        with pytest.raises(LookupFailed):
            crops(tmp_path, StubPictures(), FixedFaces([]), BytesByUrl({PICTURE: error})).portrait("A Pop Star")
    assert not list(tmp_path.iterdir())
    unreadable = crops(tmp_path, StubPictures(readable=False), FixedFaces([]), BytesByUrl({PICTURE: b"gif"}))
    assert unreadable.portrait("A Pop Star") == PICTURE
    assert "cannot be read" in caplog.text
    assert str(UnreadablePicture(PICTURE)) == PICTURE


def test_kept_files_are_made_once_written_whole_and_the_oldest_let_go(tmp_path):
    made = []

    def make(what):
        def making():
            made.append(what)
            return what.encode()

        return making

    files = KeptFiles(tmp_path, "kept/", 2, ".bin")
    first = files.url_for("one", make("one"))
    assert first.startswith("kept/") and first.endswith(".bin")
    assert files.url_for("one", make("again")) == first
    assert made == ["one"]
    files.url_for("two", make("two"))
    files.url_for("three", make("three"))
    assert len(list(tmp_path.glob("*.bin"))) == 2
    assert not list(tmp_path.glob("*.part"))
    with pytest.raises(RuntimeError):
        files.url_for("four", lambda: (_ for _ in ()).throw(RuntimeError("no")))
    assert not list(tmp_path.glob("*.part"))
