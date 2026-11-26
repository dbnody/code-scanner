"""截图坐标换算。

Tk 的坐标是逻辑像素，PIL 抓屏拿到的是物理像素；在 Windows 高 DPI（如 125%）缩放下两者
差一个比例，直接拿逻辑坐标去裁物理截图会截小、截偏，二维码就被切掉一角。
"""

from __future__ import annotations

Box = tuple[int, int, int, int]


def expand_box(box: Box, margin: int = 8, ratio: float = 0.06) -> Box:
    """向外扩一点，保证码四周的白边（静区）一起截进去。"""
    x1, y1, x2, y2 = box
    dx = max(margin, round(max(0, x2 - x1) * ratio))
    dy = max(margin, round(max(0, y2 - y1) * ratio))
    return (x1 - dx, y1 - dy, x2 + dx, y2 + dy)


def to_physical(box: Box, scale_x: float, scale_y: float, size: tuple[int, int]) -> Box:
    """逻辑坐标 → 物理像素，并裁剪到截图范围内。"""
    x1, y1, x2, y2 = box
    left = round(min(x1, x2) * scale_x)
    top = round(min(y1, y2) * scale_y)
    right = round(max(x1, x2) * scale_x)
    bottom = round(max(y1, y2) * scale_y)
    width, height = size
    left = max(0, min(left, width - 1))
    top = max(0, min(top, height - 1))
    right = max(left + 1, min(right, width))
    bottom = max(top + 1, min(bottom, height))
    return (left, top, right, bottom)


def screen_scale(logical_size: tuple[int, int], physical_size: tuple[int, int]) -> tuple[float, float]:
    """按整屏尺寸算出逻辑→物理的缩放比例。"""
    logical_w, logical_h = logical_size
    physical_w, physical_h = physical_size
    return (
        physical_w / logical_w if logical_w else 1.0,
        physical_h / logical_h if logical_h else 1.0,
    )
