"""图像预处理：灰度、二值化、锐化、反色、对比度、透视校正与自动旋转。

所有函数都接受 BGR 或灰度 ndarray，返回 3 通道 BGR，方便界面直接预览。
"""

from __future__ import annotations

from typing import Any, Iterable

from .decoder import DecodeResult, decode_image

OPTION_KEYS = ("grayscale", "binarize", "sharpen", "invert", "contrast", "perspective", "rotate")

OPTION_LABELS = {
    "grayscale": "灰度",
    "binarize": "二值化",
    "sharpen": "锐化",
    "invert": "反色",
    "contrast": "对比度增强",
    "perspective": "透视校正",
    "rotate": "自动旋转",
}


def _bgr(image: Any) -> Any:
    import cv2

    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def warp_perspective(image: Any) -> Any:
    """找出画面中最大的四边形并拉正；找不到合适的四边形时原图返回。"""
    import cv2
    import numpy as np

    source = _bgr(image)
    gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return source
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 0.05 * gray.size:
        return source
    approx = cv2.approxPolyDP(largest, 0.02 * cv2.arcLength(largest, True), True)
    if len(approx) != 4:
        return source
    points = np.array([point[0] for point in approx], dtype="float32")
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1).ravel()
    top_left, bottom_right = points[np.argmin(sums)], points[np.argmax(sums)]
    top_right, bottom_left = points[np.argmin(diffs)], points[np.argmax(diffs)]
    width = int(max(np.linalg.norm(bottom_right - bottom_left), np.linalg.norm(top_right - top_left)))
    height = int(max(np.linalg.norm(top_right - bottom_right), np.linalg.norm(top_left - bottom_left)))
    if width < 20 or height < 20:
        return source
    target = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32")
    matrix = cv2.getPerspectiveTransform(np.array([top_left, top_right, bottom_right, bottom_left], dtype="float32"), target)
    return cv2.warpPerspective(source, matrix, (width, height))


def apply_options(image: Any, options: Iterable[str] = ()) -> Any:
    """按勾选项依次处理图片。"""
    import cv2

    active = set(options)
    result = _bgr(image)
    if "perspective" in active:
        result = warp_perspective(result)
    if "grayscale" in active or "binarize" in active:
        result = cv2.cvtColor(_bgr(result), cv2.COLOR_BGR2GRAY)
    if "contrast" in active:
        result = cv2.convertScaleAbs(result, alpha=1.6, beta=-24)
    if "sharpen" in active:
        blurred = cv2.GaussianBlur(result, (0, 0), 3)
        result = cv2.addWeighted(result, 1.6, blurred, -0.6, 0)
    if "binarize" in active:
        result = cv2.adaptiveThreshold(result, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10)
    if "invert" in active:
        result = cv2.bitwise_not(result)
    return _bgr(result)


def _rotate(image: Any, angle: int) -> Any:
    import cv2

    rotate_code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}[angle]
    return cv2.rotate(image, rotate_code)


def _variants(image: Any, options: Iterable[str]) -> list[tuple[str, Any]]:
    import cv2

    active = set(options)
    base = apply_options(image, [key for key in active if key != "binarize"])
    variants: list[tuple[str, Any]] = []
    if "rotate" in active:
        variants.extend((f"自动旋转：{angle}°", _rotate(base, angle)) for angle in (90, 180, 270))
    variants.append(("灰度 + 二值化", apply_options(image, ["grayscale", "binarize"])))
    variants.append(("锐化 + 对比度增强", apply_options(image, ["sharpen", "contrast"])))
    variants.append(("反色", apply_options(image, ["invert"])))
    variants.append(("灰度 + 透视校正", apply_options(image, ["grayscale", "perspective"])))
    height, width = image.shape[:2]
    if max(height, width) < 1600:
        variants.append(("放大 2 倍", cv2.resize(base, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)))
    return variants


def decode_with_options(image: Any, options: Iterable[str] = (), hard: bool = False) -> tuple[list[DecodeResult], Any, str]:
    """返回（识别结果、用于展示的图片、预处理说明）。"""
    options = list(options)
    processed = apply_options(image, options)
    decoded = decode_image(processed)
    if decoded or not hard:
        return decoded, processed, _note(options)

    for note, variant in _variants(image, options):
        decoded = decode_image(variant)
        if decoded:
            return decoded, variant, note if not options else f"{_note(options)} → {note}"
    return [], processed, "困难模式已尝试全部增强组合"


def _note(options: Iterable[str]) -> str:
    labels = [OPTION_LABELS[key] for key in options if key in OPTION_LABELS]
    return " + ".join(labels)
