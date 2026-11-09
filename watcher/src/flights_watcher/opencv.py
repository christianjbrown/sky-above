"""Finding faces and cutting pictures with OpenCV."""

import pathlib

import cv2
import numpy

from flights_watcher.faces import Box, Picture

# OpenCV's YuNet face detector (Shiqi Yu, MIT licence, see the LICENSE beside it), from the
# OpenCV model zoo. It finds faces turned away from the camera as well as straight on.
YUNET_MODEL = pathlib.Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"

# Each face YuNet reports starts with its box: left, top, width, height.
_BOX = slice(0, 4)
_JPEG = ".jpg"


class YuNetFaces:
    """The faces YuNet is at least this confident about."""

    def __init__(self, model: pathlib.Path, confidence: float) -> None:
        self._detector = cv2.FaceDetectorYN.create(str(model), "", (0, 0), score_threshold=confidence)

    def faces(self, picture: Picture) -> list[Box]:
        self._detector.setInputSize((picture.width, picture.height))
        _, found = self._detector.detect(picture.pixels)
        return [] if found is None else [Box(*(int(value) for value in row[_BOX])) for row in found]


class OpenCvPictures:
    def decode(self, data: bytes) -> Picture | None:
        pixels: cv2.typing.MatLike | None = cv2.imdecode(numpy.frombuffer(data, numpy.uint8), cv2.IMREAD_COLOR)
        if pixels is None:
            return None
        height, width = pixels.shape[:2]
        return Picture(pixels, width, height)

    def square_jpeg(self, picture: Picture, square: Box, side: int, quality: int) -> bytes:
        cut = picture.pixels[square.top : square.top + square.height, square.left : square.left + square.width]
        scaled = cv2.resize(cut, (side, side), interpolation=cv2.INTER_AREA)
        _, encoded = cv2.imencode(_JPEG, scaled, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return encoded.tobytes()
