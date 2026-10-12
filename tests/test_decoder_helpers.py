import unittest

from scanner.decoder import _format_name, _point_xy, _position


class DecoderHelpersTest(unittest.TestCase):
    def test_point_and_format_helpers(self):
        self.assertEqual(_point_xy((1, 2)), (1.0, 2.0))
        self.assertEqual(_point_xy(type("P", (), {"x": 3, "y": 4})()), (3.0, 4.0))
        self.assertEqual(_format_name("QR_CODE"), "QR CODE")

    def test_position_is_normalized(self):
        self.assertEqual(_position([(1, 2), (3, 4)]), ((1.0, 2.0), (3.0, 4.0)))


if __name__ == "__main__":
    unittest.main()
