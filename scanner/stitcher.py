"""把打乱的二维码碎片拼回整图，再交给识别层。

前提：碎片来自同一张图规则切分出的等大矩形，方向一致，只有顺序被打乱。
拼接只依赖接缝：正确相邻的两块，边缘像素应当几乎一致。搜索用回溯（每次先填
候选最少的格子），把"接缝对不上"和"外圈不是白色静区"当作剪枝条件；找到完整
排列后立刻尝试解码，解码成功才算拼对。拼不出来时退回贪心 + 爬山，给出误差最
小的拼接图。

切分线正好落在二维码模块边界上时，接缝两侧是不同模块，像素并不相等，这类碎
片可能拼不出唯一解，此时会返回误差最小的拼接图供人工查看。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import random
import time
from typing import Sequence

import numpy as np

from .batch import read_image
from .decoder import DecodeResult, decode_image

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
MAX_FRAGMENTS = 144
EDGE_TOLERANCE = 1.5  # 接缝两侧平均灰度差小于它才允许相邻
BORDER_DARK_LIMIT = 0.02  # 外圈允许的深色像素比例


@dataclass
class StitchResult:
    image: np.ndarray
    rows: int
    cols: int
    order: tuple[int, ...]
    score: float
    decoded: list[DecodeResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.decoded)


def list_fragments(folder: str | Path) -> list[Path]:
    root = Path(folder)
    if not root.is_dir():
        raise ValueError(f"不是文件夹：{root}")
    return sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)


def load_fragments(paths: Sequence[str | Path]) -> list[np.ndarray]:
    tiles: list[np.ndarray] = []
    for path in paths:
        tile = read_image(path)
        if tile is None:
            raise ValueError(f"无法读取碎片：{Path(path).name}")
        tiles.append(tile)
    if len(tiles) < 4:
        raise ValueError("至少需要 4 块碎片")
    if len(tiles) > MAX_FRAGMENTS:
        raise ValueError(f"碎片过多（最多 {MAX_FRAGMENTS} 块）")
    if len({tile.shape for tile in tiles}) > 1:
        raise ValueError("碎片尺寸不一致，请确认它们来自同一张图且没有被缩放")
    return tiles


def _edge_profiles(tiles: Sequence[np.ndarray]) -> list[dict[str, np.ndarray]]:
    import cv2  # type: ignore

    profiles = []
    for tile in tiles:
        gray = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY).astype(np.float32)
        profiles.append(
            {
                "left": gray[:, 0],
                "right": gray[:, -1],
                "top": gray[0, :],
                "bottom": gray[-1, :],
            }
        )
    return profiles


def _cost_matrices(profiles: Sequence[dict[str, np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    count = len(profiles)
    horizontal = np.zeros((count, count), np.float32)
    vertical = np.zeros((count, count), np.float32)
    for i, first in enumerate(profiles):
        for j, second in enumerate(profiles):
            if i == j:
                continue
            horizontal[i, j] = float(np.abs(first["right"] - second["left"]).mean())
            vertical[i, j] = float(np.abs(first["bottom"] - second["top"]).mean())
    return horizontal, vertical


def _side_darkness(tiles: Sequence[np.ndarray]) -> list[dict[str, float]]:
    """每块碎片四条外边上的深色像素比例，用来判断它能否放在外圈静区上。"""
    import cv2  # type: ignore

    band = max(2, min(tiles[0].shape[:2]) // 8)
    result = []
    for tile in tiles:
        gray = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY)
        result.append(
            {
                "top": float((gray[:band] < 128).mean()),
                "bottom": float((gray[-band:] < 128).mean()),
                "left": float((gray[:, :band] < 128).mean()),
                "right": float((gray[:, -band:] < 128).mean()),
            }
        )
    return result


def _border_ok(dark: dict[str, float], row: int, col: int, rows: int, cols: int) -> bool:
    if row == 0 and dark["top"] > BORDER_DARK_LIMIT:
        return False
    if row == rows - 1 and dark["bottom"] > BORDER_DARK_LIMIT:
        return False
    if col == 0 and dark["left"] > BORDER_DARK_LIMIT:
        return False
    if col == cols - 1 and dark["right"] > BORDER_DARK_LIMIT:
        return False
    return True


def _total_cost(order: Sequence[int], rows: int, cols: int, horizontal: np.ndarray, vertical: np.ndarray) -> float:
    total = 0.0
    for row in range(rows):
        for col in range(cols):
            index = row * cols + col
            if col + 1 < cols:
                total += horizontal[order[index], order[index + 1]]
            if row + 1 < rows:
                total += vertical[order[index], order[index + cols]]
    return float(total)


def _greedy_order(rows: int, cols: int, horizontal: np.ndarray, vertical: np.ndarray, rng: random.Random) -> list[int]:
    count = rows * cols
    order = [-1] * count
    used = [False] * count
    start = rng.randrange(count)
    order[0] = start
    used[start] = True
    for position in range(1, count):
        row, col = divmod(position, cols)
        best_cost = float("inf")
        best_index = -1
        for candidate in range(count):
            if used[candidate]:
                continue
            cost = 0.0
            if col > 0:
                cost += horizontal[order[position - 1], candidate]
            if row > 0:
                cost += vertical[order[position - cols], candidate]
            if cost < best_cost:
                best_cost = cost
                best_index = candidate
        order[position] = best_index
        used[best_index] = True
    return order


def _edges_at(position: int, order: list[int], rows: int, cols: int) -> list[tuple[str, int, int]]:
    row, col = divmod(position, cols)
    edges: list[tuple[str, int, int]] = []
    if col + 1 < cols:
        edges.append(("h", order[position], order[position + 1]))
    if col > 0:
        edges.append(("h", order[position - 1], order[position]))
    if row + 1 < rows:
        edges.append(("v", order[position], order[position + cols]))
    if row > 0:
        edges.append(("v", order[position - cols], order[position]))
    return edges


def _edge_cost(kind: str, first: int, second: int, horizontal: np.ndarray, vertical: np.ndarray) -> float:
    return float(horizontal[first, second] if kind == "h" else vertical[first, second])


def _improve(order: list[int], rows: int, cols: int, horizontal: np.ndarray, vertical: np.ndarray) -> list[int]:
    count = len(order)
    for _ in range(12):
        improved = False
        for first in range(count - 1):
            for second in range(first + 1, count):
                old_edges = _edges_at(first, order, rows, cols) + _edges_at(second, order, rows, cols)
                old_cost = sum(_edge_cost(*edge, horizontal, vertical) for edge in old_edges)
                order[first], order[second] = order[second], order[first]
                new_edges = _edges_at(first, order, rows, cols) + _edges_at(second, order, rows, cols)
                new_cost = sum(_edge_cost(*edge, horizontal, vertical) for edge in new_edges)
                if new_cost < old_cost - 1e-9:
                    improved = True
                else:
                    order[first], order[second] = order[second], order[first]
        if not improved:
            break
    return order


def grid_candidates(count: int) -> list[tuple[int, int]]:
    candidates = {
        (rows, count // rows)
        for rows in range(2, count + 1)
        if count % rows == 0 and 2 <= count // rows
    }
    if not candidates:
        raise ValueError(f"{count} 块碎片无法排成矩形，请检查是否少传或多了图片")
    return sorted(candidates, key=lambda pair: (abs(pair[0] - pair[1]), pair[0] > pair[1]))


def compose(order: Sequence[int], tiles: Sequence[np.ndarray], rows: int, cols: int) -> np.ndarray:
    import cv2  # type: ignore

    height, width = tiles[0].shape[:2]
    canvas = np.full((rows * height, cols * width, 3), 255, np.uint8)
    for position, index in enumerate(order):
        row, col = divmod(position, cols)
        canvas[row * height : (row + 1) * height, col * width : (col + 1) * width] = tiles[index]
    # 二维码需要留白边，原图被切碎后静区可能已经丢失。
    quiet = max(8, int(round(max(canvas.shape[:2]) * 0.06)))
    return cv2.copyMakeBorder(canvas, quiet, quiet, quiet, quiet, cv2.BORDER_CONSTANT, value=(255, 255, 255))


def _prepare_for_decode(image: np.ndarray) -> np.ndarray:
    import cv2  # type: ignore

    height, width = image.shape[:2]
    shortest = min(height, width)
    if shortest >= 480:
        return image
    factor = min(6, max(1, int(np.ceil(480 / shortest))))
    return cv2.resize(image, (width * factor, height * factor), interpolation=cv2.INTER_NEAREST)


def _try_decode(order: Sequence[int], tiles: Sequence[np.ndarray], rows: int, cols: int) -> list[DecodeResult]:
    try:
        return decode_image(_prepare_for_decode(compose(order, tiles, rows, cols)))
    except Exception:  # noqa: BLE001 - 没有可用识别引擎时保留拼接图
        return []


def _search(
    tiles: Sequence[np.ndarray],
    rows: int,
    cols: int,
    horizontal: np.ndarray,
    vertical: np.ndarray,
    darkness: Sequence[dict[str, float]],
    *,
    use_border: bool,
    node_cap: int,
    decode_budget: int,
    deadline: float,
) -> tuple[tuple[int, ...], float, list[DecodeResult]] | None:
    """回溯搜索所有满足接缝（和外圈静区）约束的排列，边搜边解码。"""
    count = rows * cols
    next_right = [[j for j in range(count) if j != i and horizontal[i, j] <= EDGE_TOLERANCE] for i in range(count)]
    next_down = [[j for j in range(count) if j != i and vertical[i, j] <= EDGE_TOLERANCE] for i in range(count)]

    placed: dict[int, int] = {}
    used = [False] * count
    nodes = 0
    decodes = 0
    first_order: list[tuple[int, ...]] = []
    success: list[tuple[tuple[int, ...], list[DecodeResult]]] = []

    def candidates(position: int) -> list[int]:
        row, col = divmod(position, cols)
        left = placed.get(position - 1) if col > 0 else None
        up = placed.get(position - cols) if row > 0 else None
        right = placed.get(position + 1) if col + 1 < cols else None
        below = placed.get(position + cols) if row + 1 < rows else None
        allowed = next_right[left] if left is not None else None
        if up is not None:
            down = next_down[up]
            allowed = down if allowed is None else [j for j in allowed if j in set(down)]
        result = []
        for index in (allowed if allowed is not None else range(count)):
            if used[index]:
                continue
            # 先填的邻居可能在右/下方向，同样要满足接缝连续。
            if right is not None and horizontal[index, right] > EDGE_TOLERANCE:
                continue
            if below is not None and vertical[index, below] > EDGE_TOLERANCE:
                continue
            if use_border and not _border_ok(darkness[index], row, col, rows, cols):
                continue
            result.append(index)
        return result

    def visit(position: int) -> None:
        nonlocal nodes, decodes
        nodes += 1
        if success or nodes > node_cap or time.time() > deadline:
            return
        if len(placed) == count:
            order = tuple(placed[row * cols + col] for row in range(rows) for col in range(cols))
            if not first_order:
                first_order.append(order)
            if decodes < decode_budget:
                decodes += 1
                decoded = _try_decode(order, tiles, rows, cols)
                if decoded:
                    success.append((order, decoded))
            return
        best_position = -1
        best_candidates: list[int] = []
        positions = [position] if not placed else [
            pos
            for pos in range(count)
            if pos not in placed
            and ((pos % cols > 0 and pos - 1 in placed) or (pos >= cols and pos - cols in placed))
        ]
        for pos in positions:
            found = candidates(pos)
            if best_position < 0 or len(found) < len(best_candidates):
                best_position, best_candidates = pos, found
                if not found:
                    break
        for index in best_candidates:
            placed[best_position] = index
            used[index] = True
            visit(position + 1)
            used[index] = False
            del placed[best_position]
            if success or nodes > node_cap or time.time() > deadline:
                break

    visit(0)
    if success:
        return success[0][0], _total_cost(success[0][0], rows, cols, horizontal, vertical), success[0][1]
    if first_order:
        return first_order[0], _total_cost(first_order[0], rows, cols, horizontal, vertical), []
    return None


def _heuristic_orders(
    tiles: Sequence[np.ndarray],
    rows: int,
    cols: int,
    horizontal: np.ndarray,
    vertical: np.ndarray,
    restarts: int,
    seed: int,
) -> list[tuple[float, tuple[int, ...]]]:
    rng = random.Random(seed)
    seen: set[tuple[int, ...]] = set()
    results: list[tuple[float, tuple[int, ...]]] = []
    for _ in range(max(1, restarts)):
        order = _improve(_greedy_order(rows, cols, horizontal, vertical, rng), rows, cols, horizontal, vertical)
        key = tuple(order)
        if key in seen:
            continue
        seen.add(key)
        results.append((_total_cost(order, rows, cols, horizontal, vertical), key))
    results.sort(key=lambda item: item[0])
    return results


def stitch_fragments(paths: Sequence[str | Path], *, restarts: int = 8, seed: int = 0) -> StitchResult:
    """拼接碎片并尝试识别。

    paths 是碎片图片路径，顺序任意。返回拼接结果；``ok`` 为真表示已识别。
    即使没有识别出来，也会返回接缝误差最小的拼接图供人工查看。
    """
    tiles = load_fragments(paths)
    horizontal, vertical = _cost_matrices(_edge_profiles(tiles))
    darkness = _side_darkness(tiles)
    grids = grid_candidates(len(tiles))
    best: StitchResult | None = None
    deadline = time.time() + 6.0

    for rows, cols in grids:
        if time.time() > deadline - 0.2:
            break
        # 优先按"外圈静区必须白色"搜索，失败再放宽为只约束接缝。
        for use_border, node_cap in ((True, 60_000), (False, 120_000)):
            if time.time() > deadline - 0.2:
                break
            found = _search(
                tiles,
                rows,
                cols,
                horizontal,
                vertical,
                darkness,
                use_border=use_border,
                node_cap=node_cap,
                decode_budget=6,
                deadline=min(deadline, time.time() + 2.0),
            )
            if found is None:
                continue
            order, score, decoded = found
            candidate = StitchResult(compose(order, tiles, rows, cols), rows, cols, order, score, decoded)
            if candidate.ok:
                return candidate
            if best is None or score < best.score:
                best = candidate

    for rows, cols in grids[:3]:
        if time.time() > deadline:
            break
        orders = _heuristic_orders(tiles, rows, cols, horizontal, vertical, 4 if len(tiles) <= 25 else 2, seed)
        for score, order in orders:
            candidate = StitchResult(compose(order, tiles, rows, cols), rows, cols, order, score)
            if best is None or score < best.score:
                best = candidate
            decoded = _try_decode(order, tiles, rows, cols)
            if decoded:
                candidate.decoded = decoded
                return candidate

    if best is None:
        rows, cols = grids[0]
        order = _greedy_order(rows, cols, horizontal, vertical, random.Random(seed))
        best = StitchResult(
            compose(order, tiles, rows, cols),
            rows,
            cols,
            tuple(order),
            _total_cost(order, rows, cols, horizontal, vertical),
        )
    return best
