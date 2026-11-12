import unittest
from pathlib import Path

from scanner import theme


class ThemeAssetTest(unittest.TestCase):
    def test_icon_assets_exist(self):
        png = theme.asset("icon.png")
        ico = theme.asset("icon.ico")
        self.assertTrue(png.exists(), png)
        self.assertTrue(ico.exists(), ico)

        from PIL import Image

        with Image.open(png) as image:
            self.assertEqual(image.size, (256, 256))
        with Image.open(ico) as image:
            self.assertIn((16, 16), image.info.get("sizes", set()))

    def test_spec_embeds_icon(self):
        spec = Path(__file__).resolve().parent.parent / "CodeScanner.spec"
        text = spec.read_text(encoding="utf-8")
        self.assertIn("icon='assets/icon.ico'", text)
        self.assertIn("assets/icon.png", text)


if __name__ == "__main__":
    unittest.main()
