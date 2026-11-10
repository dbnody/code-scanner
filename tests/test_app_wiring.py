import unittest


class AppWiringTest(unittest.TestCase):
    def test_app_exposes_new_entry_points(self):
        import scanner.app as app

        for name in (
            "open_image",
            "batch_decode",
            "scan_folder_dialog",
            "screenshot",
            "paste_clipboard",
            "retry_failed",
            "cancel_batch",
            "_on_drop",
            "_show_decoded",
            "_on_row_select",
        ):
            self.assertTrue(callable(getattr(app.ScannerApp, name, None)), name)
        self.assertTrue(hasattr(app, "RegionSelector"))


if __name__ == "__main__":
    unittest.main()
