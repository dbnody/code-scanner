"""生成 assets/icon.ico 与 assets/icon.png（珊瑚色圆角底 + 白色二维码）。"""

from pathlib import Path
import random

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
S = 1024
TOP = (255, 138, 120)
BOTTOM = (230, 66, 56)
MODULE = (216, 72, 60)
GRID = 9
FINDERS = ((0, 0), (GRID - 3, 0), (0, GRID - 3))


def data_modules() -> list[tuple[int, int]]:
    reserved = set()
    for col, row in FINDERS:
        for dc in range(3):
            for dr in range(3):
                reserved.add((col + dc, row + dr))
    # 定位图案外留一格白色隔离带
    ring = set()
    for col, row in reserved:
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                ring.add((col + dc, row + dr))
    rng = random.Random(7)
    cells = [(col, row) for col in range(GRID) for row in range(GRID) if (col, row) not in ring]
    return [cell for cell in cells if rng.random() < 0.5]



def gradient(size: int) -> Image.Image:
    image = Image.new("RGB", (1, size))
    for y in range(size):
        ratio = y / max(1, size - 1)
        image.putpixel((0, y), tuple(round(a + (b - a) * ratio) for a, b in zip(TOP, BOTTOM)))
    return image.resize((size, size))


def build() -> Image.Image:
    canvas = gradient(S).convert("RGBA")
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.23), fill=255)
    canvas.putalpha(mask)

    tile = round(S * 0.64)
    left = (S - tile) // 2
    top = (S - tile) // 2
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((left, top, left + tile, top + tile), radius=int(tile * 0.13), fill=(255, 255, 255))

    inset = tile * 0.11
    inner = tile - inset * 2
    module = inner / GRID
    origin = (left + inset, top + inset)

    def block(col: int, row: int, color: tuple[int, int, int], span: int = 1) -> None:
        x0 = origin[0] + col * module
        y0 = origin[1] + row * module
        draw.rectangle((x0, y0, x0 + module * span - module * 0.06, y0 + module * span - module * 0.06), fill=color)

    for col, row in ((0, 0), (GRID - 3, 0), (0, GRID - 3)):
        for dc in range(3):
            for dr in range(3):
                block(col + dc, row + dr, MODULE)
        block(col + 1, row + 1, (255, 255, 255))

    for col, row in data_modules():
        if col < GRID and row < GRID:
            block(col, row, MODULE)

    return canvas.resize((256, 256), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    icon = build()
    icon.save(ASSETS / "icon.png")
    icon.save(
        ASSETS / "icon.ico",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)],
    )
    print("icon written:", ASSETS / "icon.ico", ASSETS / "icon.png")


if __name__ == "__main__":
    main()
