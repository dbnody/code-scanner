import unittest

import numpy as np

from scanner.annotate import annotate
from scanner.decoder import DecodeResult


def _has_color(pil, color) -> bool:
    return bool(np.any(np.all(np.array(pil) == color, axis=-1)))


class AnnotateTest(unittest.TestCase):
    def setUp(self):
        self.image = np.full((200, 240, 3), 255, np.uint8)
        self.position = ((20, 20), (100, 20), (100, 90), (20, 90))
        self.result = DecodeResult("https://example.com", "QRCode", self.position)

    def test_returns_pil_image_and_draws_box(self):
        pil = annotate(self.image, [self.result])
        self.assertEqual(pil.size, (240, 200))
        self.assertTrue(_has_color(pil, (255, 59, 48)))

    def test_highlighted_result_uses_other_color(self):
        pil = annotate(self.image, [self.result], highlight=self.position)
        self.assertTrue(_has_color(pil, (255, 214, 0)))

    def test_ignores_results_without_position(self):
        pil = annotate(self.image, [DecodeResult("plain", "QRCode")])
        self.assertFalse(_has_color(pil, (255, 59, 48)))


if __name__ == "__main__":
    unittest.main()
