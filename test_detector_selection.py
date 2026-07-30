import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory
from unittest.mock import patch

import app
from chapter_contract import SegmentationMode


class DetectorSelectionTest(unittest.TestCase):
    def test_process_chapter_builds_a_detector_for_each_request_mode(self):
        captured_options = []

        class RecordingDetector:
            def __init__(self, options):
                captured_options.append(options)

            def parse_dir(self, _image_path):
                return {"pages": [{"filename": "001.png", "panels": []}]}

        with TemporaryDirectory() as directory, patch.multiple(
            app,
            DATA_DIR=app.Path(directory),
            IMAGES_DIR=app.Path(directory) / "images",
            JSONS_DIR=app.Path(directory) / "jsons",
            Kumiko=RecordingDetector,
            download_lmages=lambda _url, _path: 1,
            save_file=lambda _info, path: app.Path(path).write_text("{}"),
        ):
            app.process_chapter(
                "https://opchapters.com/chapter/standard",
                SegmentationMode.STANDARD,
            )
            app.process_chapter(
                "https://opchapters.com/chapter/premium",
                SegmentationMode.GPT_5_6_LAYOUT,
            )

        self.assertEqual(captured_options[0]["panel_llm_mode"], "off")
        self.assertEqual(captured_options[1]["panel_llm_mode"], "always")

    def test_extractions_with_different_modes_remain_serialized(self):
        state_lock = threading.Lock()
        active = 0
        maximum_active = 0
        received_modes = []

        def extractor(_chapter_url, mode):
            nonlocal active, maximum_active
            with state_lock:
                active += 1
                maximum_active = max(maximum_active, active)
                received_modes.append(mode)
            time.sleep(0.03)
            with state_lock:
                active -= 1

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    app.run_extraction,
                    extractor,
                    f"https://opchapters.com/chapter/{mode.value}",
                    mode,
                )
                for mode in SegmentationMode
            ]
            for future in futures:
                future.result()

        self.assertEqual(maximum_active, 1)
        self.assertCountEqual(received_modes, list(SegmentationMode))


if __name__ == "__main__":
    unittest.main()
