import unittest
from unittest.mock import Mock

from rpi360 import FrameOutput
from rpi360.adapters.opencv_viewer import (
    _handle_key,
    _ViewerState,
    viewer_settings,
)


class ViewerTests(unittest.TestCase):
    def test_user_display_names_separate_projection_from_stage(self):
        self.assertEqual(
            viewer_settings("perspective"),
            ("perspective", FrameOutput.VIEW),
        )
        self.assertEqual(
            viewer_settings("equi_blended"),
            ("stereographic", FrameOutput.EQUI_BLENDED),
        )

    def test_keys_one_through_eight_select_every_public_output(self):
        player = Mock()
        player.view.projection = "perspective"
        player.view.fov = 90.0
        state = _ViewerState(FrameOutput.VIEW)
        expected = {
            "1": FrameOutput.VIEW,
            "2": FrameOutput.VIEW,
            "3": FrameOutput.VIEW,
            "4": FrameOutput.EQUI_BLENDED,
            "5": FrameOutput.EQUI_1,
            "6": FrameOutput.EQUI_2,
            "7": FrameOutput.CAMERA0,
            "8": FrameOutput.CAMERA1,
        }
        for key, output in expected.items():
            _handle_key(
                player,
                ord(key),
                viewer=state,
                rotation_step=3.0,
                seek_step=5.0,
            )
            self.assertEqual(state.display, output)


if __name__ == "__main__":
    unittest.main()
