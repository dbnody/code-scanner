"""离线条码识别适配层。

主引擎是 zxing-cpp，支持 QR、Data Matrix、Aztec、PDF417、MaxiCode
以及常见的一维条码。没有安装 zxing-cpp 时，会尽量回退到 OpenCV 的
QR/条码识别器，方便开发环境先启动界面。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class DecodeResult:
    text: str
    format_name: str
    position: tuple[tuple[float, float], ...] = ()


def _point_xy(point: Any) -> Optional[tuple[float, float]]:
    """兼容 zxing-cpp 不同版本返回的 Point 对象。"""
    if point is None:
        return None
    if isinstance(point, (tuple, list)) and len(point) >= 2:
        return float(point[0]), float(point[1])
    for x_name, y_name in (("x", "y"), ("X", "Y")):
        if hasattr(point, x_name) and hasattr(point, y_name):
            return float(getattr(point, x_name)), float(getattr(point, y_name))
    return None


def _position(value: Any) -> tuple[tuple[float, float], ...]:
    if value is None:
        return ()
    # zxing-cpp 的 Position 通常可迭代；有些版本暴露 top_left 等属性。
    try:
        points = [_point_xy(point) for point in value]
    except TypeError:
        points = []
    if not points:
        names = ("top_left", "top_right", "bottom_right", "bottom_left")
        points = [_point_xy(getattr(value, name, None)) for name in names]
    return tuple(point for point in points if point is not None)


def _format_name(value: Any) -> str:
    if value is None:
        return "未知"
    name = getattr(value, "name", None)
    if name:
        return str(name).replace("_", " ")
    return str(value).replace("BarcodeFormat.", "").replace("_", " ")


def _decode_zxing(image: Any) -> list[DecodeResult]:
    import zxingcpp  # type: ignore

    decoded: list[DecodeResult] = []
    for item in zxingcpp.read_barcodes(image):
        text = getattr(item, "text", "") or ""
        if not text:
            continue
        decoded.append(
            DecodeResult(
                text=text,
                format_name=_format_name(getattr(item, "format", None)),
                position=_position(getattr(item, "position", None)),
            )
        )
    return decoded


def _decode_opencv(image: Any) -> list[DecodeResult]:
    import cv2  # type: ignore

    decoded: list[DecodeResult] = []
    qr = cv2.QRCodeDetector()
    try:
        ok, values, points, _ = qr.detectAndDecodeMulti(image)
        if ok and values is not None:
            for index, value in enumerate(values):
                if value:
                    corners = points[index] if points is not None else []
                    decoded.append(
                        DecodeResult(
                            text=value,
                            format_name="QR CODE",
                            position=tuple((float(p[0]), float(p[1])) for p in corners),
                        )
                    )
    except (AttributeError, cv2.error):
        pass

    # opencv-contrib 的 BarcodeDetector 可识别 Code128、EAN 等一维码。
    barcode_detector = getattr(cv2, "barcode", None)
    if barcode_detector is not None and hasattr(barcode_detector, "BarcodeDetector"):
        try:
            detector = barcode_detector.BarcodeDetector()
            ok, values, _, points = detector.detectAndDecode(image)
            if ok and values is not None:
                for index, value in enumerate(values):
                    if value:
                        corners = points[index] if points is not None else []
                        decoded.append(
                            DecodeResult(
                                text=value,
                                format_name="BARCODE",
                                position=tuple((float(p[0]), float(p[1])) for p in corners),
                            )
                        )
        except (AttributeError, cv2.error):
            pass
    return decoded


def decode_image(image: Any) -> list[DecodeResult]:
    """识别一张 BGR/RGB numpy 图像，结果按图像中的顺序返回。"""
    try:
        return _decode_zxing(image)
    except (ImportError, ModuleNotFoundError):
        return _decode_opencv(image)


def decode_image_file(path: str) -> tuple[Any, list[DecodeResult]]:
    """读取图片并识别，返回 (BGR 图像, 结果列表)。"""
    import cv2  # type: ignore

    image = cv2.imread(path)
    if image is None:
        raise ValueError(f"无法读取图片：{path}")
    return image, decode_image(image)


def backend_status() -> str:
    try:
        import zxingcpp  # noqa: F401, PLC0415

        return "ZXing-C++（离线多码）"
    except ImportError:
        try:
            import cv2  # noqa: F401, PLC0415

            return "OpenCV 回退模式（建议安装 zxing-cpp）"
        except ImportError:
            return "未安装图像识别依赖"
