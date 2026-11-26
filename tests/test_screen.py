import unittest

from scanner.screen import expand_box, screen_scale, to_physical


class ScreenScaleTest(unittest.TestCase):
    def test_screen_scale_matches_dpi(self):
        self.assertEqual(screen_scale((1536, 864), (1920, 1080)), (1.25, 1.25))
        self.assertEqual(screen_scale((1920, 1080), (1920, 1080)), (1.0, 1.0))

    def test_expand_box_grows_with_margin(self):
        self.assertEqual(expand_box((100, 100, 300, 200)), (88, 92, 312, 208))

    def test_expand_box_keeps_small_selection(self):
        box = expand_box((10, 10, 20, 20), margin=8, ratio=0.06)
        self.assertEqual(box, (2, 2, 28, 28))

    def test_to_physical_scales_coordinates(self):
        self.assertEqual(to_physical((100, 100, 400, 300), 1.25, 1.25, (1920, 1080)), (125, 125, 500, 375))

    def test_to_physical_clamps_to_screen(self):
        self.assertEqual(to_physical((-50, -50, 5000, 5000), 1.25, 1.25, (1920, 1080)), (0, 0, 1920, 1080))

    def test_to_physical_keeps_degenerate_box(self):
        left, top, right, bottom = to_physical((30, 30, 30, 30), 1.0, 1.0, (100, 100))
        self.assertEqual((right - left, bottom - top), (1, 1))


if __name__ == "__main__":
    unittest.main()
