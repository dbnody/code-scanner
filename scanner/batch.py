"""图片文件读取与文件夹扫描：递归找图片，按文件名或修改时间排序。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES


def read_image(path: str | Path) -> Any:
    """读取图片；走 imdecode 以兼容 Windows 中文/非 ASCII 路径。"""
    import cv2
    import numpy as np

    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def scan_folder(root: str | Path, recursive: bool = True, sort_by: str = "name") -> list[Path]:
    folder = Path(root)
    paths = [path for path in (folder.rglob("*") if recursive else folder.glob("*")) if path.is_file() and is_image(path)]
    if sort_by == "mtime":
        paths.sort(key=lambda path: (path.stat().st_mtime, str(path).lower()))
    else:
        paths.sort(key=lambda path: str(path.relative_to(folder)).lower())
    return paths


def relative_source(path: str | Path, root: str | Path) -> str:
    try:
        return str(Path(path).relative_to(root)).replace("\\", "/")
    except ValueError:
        return Path(path).name
