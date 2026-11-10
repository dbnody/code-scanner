import tempfile
import unittest
from pathlib import Path

import numpy as np


def _write_qr(text: str, path: Path) -> None:
    import cv2
    import zxingcpp

    barcode = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.QRCode)
    modules = np.asarray(zxingcpp.write_barcode_to_image(barcode))
    modules = np.where(modules < 128, 0, 255).astype(np.uint8)
    image = np.kron(modules, np.ones((8, 8), np.uint8))
    cv2.imwrite(str(path), np.pad(image, 32, constant_values=255))


class BatchDecodeTest(unittest.TestCase):
    def test_decodes_files_in_given_order(self):
        from scanner.decoder import decode_image_file

        texts = ["https://example.com/one", "https://example.com/two", "批量识别-第三张"]
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for index, text in enumerate(texts):
                path = Path(folder) / f"{index + 10}.png"
                _write_qr(text, path)
                paths.append(path)
            # 故意打乱传入顺序，结果必须跟随传入顺序而不是文件名顺序
            paths = [paths[1], paths[0], paths[2]]
            decoded = [decode_image_file(str(path))[1][0].text for path in paths]
        self.assertEqual(decoded, [texts[1], texts[0], texts[2]])


if __name__ == "__main__":
    unittest.main()
