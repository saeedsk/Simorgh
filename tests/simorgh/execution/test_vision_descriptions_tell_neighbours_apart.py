"""`look_at_image` reads a file that exists; `camera_describe` takes new stills.

Stage 17 selection stress, 2026-10-27 (docs/findings/2026-10-27-guardrails-
sidecars-and-tokens.md section 1): asked to look at a picture already saved
under workspace/cameras/, the model took a new camera snapshot. Neither
description said which tool a file on disk belongs to. These pin the facts,
not the wording.
"""

from __future__ import annotations

import unittest

from simorgh.execution.vision import CameraDescribeTool, LookAtImageTool


class LookAtImage(unittest.TestCase):
    def test_reads_files_that_already_exist_saved_snapshots_included(self):
        text = LookAtImageTool.description.lower()
        self.assertIn("already exist on disk", text)
        self.assertIn("saved camera snapshot", text)

    def test_takes_no_new_picture_and_names_the_tools_that_do(self):
        text = LookAtImageTool.description.lower()
        self.assertIn("takes no new picture", text)
        self.assertIn("cam_snapshot", text)
        self.assertIn("camera_describe", text)


class CameraDescribe(unittest.TestCase):
    def test_is_a_live_camera_and_sends_a_saved_file_to_look_at_image(self):
        text = CameraDescribeTool.description.lower()
        self.assertIn("live camera", text)
        self.assertIn("new stills", text)
        self.assertIn("look_at_image", text)


if __name__ == "__main__":
    unittest.main()
