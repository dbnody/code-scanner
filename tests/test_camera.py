import unittest

import numpy as np

from scanner.camera import CameraGate, offset_results, roi_crop
from scanner.decoder import DecodeResult


def _result(text: str, position=()) -> DecodeResult:
    return DecodeResult(text, "QRCode", position)


class CameraGateTest(unittest.TestCase):
    def test_requires_consecutive_votes(self):
        gate = CameraGate(cooldown=5, votes=2)
        code = [_result("A")]
        self.assertEqual(gate.observe(code, now=0.0), [])
        self.assertEqual([item.text for item in gate.observe(code, now=0.1)], ["A"])

    def test_missing_frame_resets_votes(self):
        gate = CameraGate(cooldown=5, votes=2)
        code = [_result("B")]
        gate.observe(code, now=0.0)
        gate.observe([], now=0.1)
        self.assertEqual(gate.observe(code, now=0.2), [])
        self.assertEqual([item.text for item in gate.observe(code, now=0.3)], ["B"])

    def test_cooldown_blocks_repeat(self):
        gate = CameraGate(cooldown=2, votes=1)
        code = [_result("C")]
        self.assertEqual([item.text for item in gate.observe(code, now=0.0)], ["C"])
        self.assertEqual(gate.observe(code, now=1.0), [])
        self.assertEqual([item.text for item in gate.observe(code, now=2.1)], ["C"])

    def test_different_codes_are_independent(self):
        gate = CameraGate(cooldown=5, votes=1)
        seen = [_result("D"), _result("E")]
        self.assertEqual(sorted(item.text for item in gate.observe(seen, now=0.0)), ["D", "E"])

    def test_reset_clears_votes(self):
        gate = CameraGate(cooldown=5, votes=2)
        code = [_result("F")]
        gate.observe(code, now=0.0)
        gate.reset()
        self.assertEqual(gate.observe(code, now=0.1), [])


class RoiTest(unittest.TestCase):
    def test_crop_center_and_offset(self):
        frame = np.zeros((100, 200, 3), np.uint8)
        crop, (dx, dy) = roi_crop(frame, ratio=0.6)
        self.assertEqual(crop.shape, (60, 120, 3))
        self.assertEqual((dx, dy), (40, 20))

    def test_offset_results_shifts_positions(self):
        decoded = [_result("G", ((0, 0), (10, 5)))]
        shifted = offset_results(decoded, 40, 20)
        self.assertEqual(shifted[0].position, ((40, 20), (50, 25)))
        self.assertEqual(shifted[0].text, "G")

    def test_offset_without_position_and_zero_offset(self):
        decoded = [_result("H")]
        self.assertEqual(offset_results(decoded, 0, 0), decoded)
        self.assertEqual(offset_results(decoded, 5, 5)[0].position, ())


if __name__ == "__main__":
    unittest.main()
