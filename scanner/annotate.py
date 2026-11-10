"""在预览图上标注每个码的位置、码制和内容。"""

from __future__ import annotations

from typing import Any, Iterable

from .decoder import DecodeResult

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _font(size: int) -> Any:
    from PIL import ImageFont

    for candidate in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def annotate(image: Any, results: Iterable[DecodeResult], highlight: Any = None) -> Any:
    """返回画好码框的 PIL 图片；highlight 为需要突出显示的码位置。"""
    import cv2
    from PIL import Image, ImageDraw

    pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    font = _font(max(14, pil.width // 60))
    thickness = max(2, pil.width // 400)
    highlight_key = tuple(highlight) if highlight else None
    for result in results:
        if len(result.position) < 3:
            continue
        points = [(float(x), float(y)) for x, y in result.position]
        color = (255, 214, 0) if highlight_key and tuple(result.position) == highlight_key else (255, 59, 48)
        draw.line(points + [points[0]], fill=color, width=thickness)
        label = f"{result.format_name} · {result.text[:28]}"
        left, top = points[0]
        box = draw.textbbox((0, 0), label, font=font)
        width, height = box[2] - box[0], box[3] - box[1]
        x = max(0, min(int(left), pil.width - width - 10))
        y = max(0, int(top) - height - 14)
        draw.rectangle((x, y, x + width + 8, y + height + 8), fill=color)
        draw.text((x + 4, y + 2), label, font=font, fill=(32, 32, 32))
    return pil
