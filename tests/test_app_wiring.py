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
            "_fill_detail",
            "copy_selected",
            "_copy_detail_field",
            "edit_template",
            "_write_export",
            "save_current_frame",
            "_on_camera_results",
        ):
            self.assertTrue(callable(getattr(app.ScannerApp, name, None)), name)
        self.assertTrue(hasattr(app, "RegionSelector"))
        self.assertTrue(hasattr(app, "ExportDialog"))
        self.assertTrue(callable(getattr(app, "render_copy", None)))
        self.assertTrue(callable(getattr(app, "CameraGate", None)))


if __name__ == "__main__":
    unittest.main()
