import unittest

import cv2
import numpy as np

from scanner.decoder import decode_image
from scanner.preprocess import OPTION_KEYS, apply_options, decode_with_options, warp_perspective


def _qr_image(text: str, scale: int = 8, pad: int = 32) -> np.ndarray:
    import zxingcpp

    barcode = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.QRCode)
    modules = np.asarray(zxingcpp.write_barcode_to_image(barcode))
    modules = np.where(modules < 128, 0, 255).astype(np.uint8)
    image = np.kron(modules, np.ones((scale, scale), np.uint8))
    return cv2.cvtColor(np.pad(image, pad, constant_values=255), cv2.COLOR_GRAY2BGR)


class PreprocessTest(unittest.TestCase):
    def test_every_option_keeps_bgr_shape(self):
        image = _qr_image("https://example.com/preprocess")
        for key in OPTION_KEYS:
            with self.subTest(option=key):
                result = apply_options(image, [key])
                self.assertEqual(result.shape[2], 3)
                self.assertEqual(result.dtype, np.uint8)

    def test_binarize_is_black_and_white(self):
        result = apply_options(_qr_image("bin"), ["binarize"])
        values = set(np.unique(cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)).tolist())
        self.assertTrue(values.issubset({0, 255}), values)

    def test_invert_changes_pixels(self):
        image = _qr_image("invert")
        self.assertFalse(np.array_equal(apply_options(image, ["invert"]), image))

    def test_warp_without_quad_returns_same_size(self):
        blank = np.full((120, 160, 3), 255, np.uint8)
        self.assertEqual(warp_perspective(blank).shape, blank.shape)

    def test_decode_with_options_reads_qr(self):
        image = _qr_image("https://example.com/options")
        decoded, processed, note = decode_with_options(image, ["grayscale", "sharpen"], hard=False)
        self.assertEqual([item.text for item in decoded], ["https://example.com/options"])
        self.assertEqual(processed.shape[2], 3)
        self.assertIn("灰度", note)

    def test_plain_decode_still_works(self):
        image = _qr_image("plain")
        self.assertEqual([item.text for item in decode_image(image)], ["plain"])

    def test_hard_mode_reports_when_nothing_found(self):
        blank = np.full((160, 160, 3), 120, np.uint8)
        decoded, processed, note = decode_with_options(blank, [], hard=True)
        self.assertEqual(decoded, [])
        self.assertEqual(processed.shape[2], 3)
        self.assertIn("困难", note)

    def test_rotate_option_does_not_crash(self):
        image = _qr_image("rotate")
        decoded, _processed, _note = decode_with_options(image, ["rotate"], hard=True)
        self.assertEqual([item.text for item in decoded], ["rotate"])


if __name__ == "__main__":
    unittest.main()
