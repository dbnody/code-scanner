import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from scanner.batch import is_image, read_image, relative_source, scan_folder


def _touch(path: Path, value: int = 255) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.full((8, 8, 3), value, np.uint8)).save(str(path))


class BatchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _touch(self.root / "a.png")
        _touch(self.root / "sub" / "b.jpg")
        _touch(self.root / "sub" / "deep" / "c.webp")
        (self.root / "notes.txt").write_text("not an image", encoding="utf-8")
        (self.root / "sub" / "data.bin").write_bytes(b"\x00")

    def tearDown(self):
        self._tmp.cleanup()

    def test_recursive_scan_skips_non_images(self):
        names = [relative_source(path, self.root) for path in scan_folder(self.root)]
        self.assertEqual(names, ["a.png", "sub/b.jpg", "sub/deep/c.webp"])

    def test_non_recursive_scan(self):
        names = [relative_source(path, self.root) for path in scan_folder(self.root, recursive=False)]
        self.assertEqual(names, ["a.png"])

    def test_sort_by_mtime(self):
        first = self.root / "a.png"
        middle = self.root / "sub" / "b.jpg"
        last = self.root / "sub" / "deep" / "c.webp"
        os.utime(first, (1_600_000_000, 1_600_000_000))
        os.utime(middle, (1_650_000_000, 1_650_000_000))
        os.utime(last, (1_700_000_000, 1_700_000_000))
        names = [relative_source(path, self.root) for path in scan_folder(self.root, sort_by="mtime")]
        self.assertEqual(names[0], "a.png")
        self.assertEqual(names[-1], "sub/deep/c.webp")

    def test_is_image_is_case_insensitive(self):
        self.assertTrue(is_image(Path("photo.JPG")))
        self.assertFalse(is_image(Path("photo.gif")))

    def test_read_image_supports_unicode_path(self):
        path = self.root / "中文 图片.png"
        _touch(path, 200)
        image = read_image(path)
        self.assertIsNotNone(image)
        self.assertEqual(image.shape, (8, 8, 3))
        self.assertIsNone(read_image(self.root / "missing.png"))


if __name__ == "__main__":
    unittest.main()
