import random
import tempfile
import unittest
from pathlib import Path

import numpy as np


def _make_qr(text: str, module_scale: int = 8, quiet_modules: int = 4) -> np.ndarray:
    import zxingcpp

    barcode = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.QRCode)
    modules = np.asarray(zxingcpp.write_barcode_to_image(barcode))
    modules = np.where(modules < 128, 0, 255).astype(np.uint8)
    image = np.kron(modules, np.ones((module_scale, module_scale), np.uint8))
    return np.pad(image, quiet_modules * module_scale, constant_values=255)


def _cut(image: np.ndarray, grid: int, shuffle_seed: int) -> list[np.ndarray]:
    cell = min(image.shape[:2]) // grid
    image = image[: cell * grid, : cell * grid]
    tiles = [image[row * cell : (row + 1) * cell, col * cell : (col + 1) * cell] for row in range(grid) for col in range(grid)]
    random.Random(shuffle_seed).shuffle(tiles)
    return tiles


class StitcherTest(unittest.TestCase):
    def test_rebuilds_shuffled_qr(self):
        import cv2

        from scanner.stitcher import stitch_fragments

        text = "https://example.com/stitch-test"
        tiles = _cut(_make_qr(text), 4, shuffle_seed=7)
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for index, tile in enumerate(tiles):
                path = Path(folder) / f"{index:02d}.png"
                cv2.imwrite(str(path), tile)
                paths.append(path)
            result = stitch_fragments(paths, restarts=8)

        self.assertTrue(result.ok, "碎片拼接后未能识别出二维码")
        self.assertEqual((result.rows, result.cols), (4, 4))
        self.assertEqual(result.decoded[0].text, text)

    def test_rejects_inconsistent_sizes(self):
        from scanner.stitcher import load_fragments

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.png").write_bytes(b"")
            (root / "b.png").write_bytes(b"")
            with self.assertRaises(ValueError):
                load_fragments([root / "a.png", root / "b.png"])


if __name__ == "__main__":
    unittest.main()
