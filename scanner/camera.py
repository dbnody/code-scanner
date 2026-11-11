"""摄像头连续扫描：ROI 裁剪、多帧投票、同码冷却。"""

from __future__ import annotations

from typing import Any

from .decoder import DecodeResult


def roi_crop(frame: Any, ratio: float = 0.6) -> tuple[Any, tuple[int, int]]:
    """裁出画面中间区域，返回（裁剪图、左上角偏移）。"""
    height, width = frame.shape[:2]
    box_w, box_h = int(width * ratio), int(height * ratio)
    x0 = max(0, (width - box_w) // 2)
    y0 = max(0, (height - box_h) // 2)
    return frame[y0:y0 + box_h, x0:x0 + box_w], (x0, y0)


def offset_results(decoded: list[DecodeResult], dx: int, dy: int) -> list[DecodeResult]:
    if not dx and not dy:
        return decoded
    return [
        DecodeResult(
            item.text,
            item.format_name,
            tuple((x + dx, y + dy) for x, y in item.position) if item.position else (),
        )
        for item in decoded
    ]


class CameraGate:
    """连续 N 帧一致才确认，确认后同一内容在冷却时间内不再重复记录。"""

    def __init__(self, cooldown: float = 3.0, votes: int = 2) -> None:
        self.cooldown = max(0.0, float(cooldown))
        self.votes = max(1, int(votes))
        self._counts: dict[tuple[str, str], int] = {}
        self._last: dict[tuple[str, str], float] = {}

    def reset(self) -> None:
        self._counts.clear()
        self._last.clear()

    def observe(self, decoded: list[DecodeResult], now: float) -> list[DecodeResult]:
        seen: set[tuple[str, str]] = set()
        confirmed: list[DecodeResult] = []
        for item in decoded:
            key = (item.format_name, item.text)
            seen.add(key)
            self._counts[key] = self._counts.get(key, 0) + 1
            last = self._last.get(key)
            cooled = last is None or now - last >= self.cooldown
            if self._counts[key] >= self.votes and cooled:
                confirmed.append(item)
                self._counts[key] = 0
                self._last[key] = now
        for key in list(self._counts):
            if key not in seen:
                self._counts[key] = 0
        return confirmed
