import unittest
from unittest import mock

import numpy as np
from rpi360.common.rendering import (
    RenderSession,
    blend_equirectangular_mapper,
    camera1_mount_rotation,
    equirectangular_pixels_to_unit_rays,
    project_unit_rays_to_fisheye,
    render_perspective,
    render_stereographic,
    stereographic_pixels_to_unit_rays,
    stitch_equirectangular,
    stitch_equirectangular_stages,
)
from rpi360.common.types import (
    CameraCalibration,
    OrientationState,
    ViewConfig,
    rotation_matrix_from_euler,
)

from tests.helpers import sample_calibration


def longitude_panorama(width=360, height=180):
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 0] = (
        np.arange(width, dtype=np.uint32)[None, :] * 255 // (width - 1)
    ).astype(np.uint8)
    image[:, :, 1] = 80
    image[:, :, 2] = 255 - image[:, :, 0]
    return image


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.calibration = sample_calibration()
        self.frame0 = np.zeros((64, 64, 3), dtype=np.uint8)
        self.frame0[:, :] = (255, 20, 10)
        self.frame1 = np.zeros((64, 64, 3), dtype=np.uint8)
        self.frame1[:, :] = (5, 30, 240)

    def test_equirectangular_shape_type_and_coverage(self):
        image = stitch_equirectangular(
            self.frame0, self.frame1, self.calibration, 160, 80
        )
        self.assertEqual(image.shape, (80, 160, 3))
        self.assertEqual(image.dtype, np.uint8)
        self.assertGreater(np.count_nonzero(image), image.size // 2)

    def test_equirectangular_rays_match_mapper_pixel_convention(self):
        rays = equirectangular_pixels_to_unit_rays(4, 2)
        np.testing.assert_allclose(rays[0, 0], [0.0, -1.0, 0.0], atol=1e-12)
        np.testing.assert_allclose(rays[1, 2], [0.0, 0.0, 1.0], atol=1e-12)

    def test_camera1_mount_is_exactly_180_degrees(self):
        expected = rotation_matrix_from_euler(180.0, 0.0, 180.0)
        np.testing.assert_allclose(camera1_mount_rotation(), expected, atol=1e-12)

    def test_equirectangular_stages_are_individually_observable(self):
        stages = stitch_equirectangular_stages(
            self.frame0, self.frame1, self.calibration, 160, 80
        )
        self.assertEqual(stages.equi_1.shape, (80, 160, 3))
        self.assertEqual(stages.equi_2.shape, (80, 160, 3))
        self.assertEqual(stages.equi_blended.shape, (80, 160, 3))
        self.assertFalse(np.array_equal(stages.equi_1, stages.equi_2))

    def test_camera_projection_uses_mapper_y_down_coordinates(self):
        rays = np.array([[0.0, 1.0, 1.0], [0.0, -1.0, 1.0]])
        map_x, map_y, valid, _ = project_unit_rays_to_fisheye(
            rays, self.calibration.camera0, 64, 64
        )
        self.assertTrue(np.all(valid))
        self.assertGreater(map_y[0], self.calibration.camera0.K[1, 2])
        self.assertLess(map_y[1], self.calibration.camera0.K[1, 2])

    def test_camera_projection_rejects_rays_outside_physical_fisheye_fov(self):
        calibration = CameraCalibration(
            200,
            100,
            np.array(
                [
                    [10.0, 0.0, 100.0],
                    [0.0, 10.0, 50.0],
                    [0.0, 0.0, 1.0],
                ]
            ),
            np.zeros(4),
            fisheye_fov_deg=210.0,
        )
        theta = np.deg2rad([100.0, 106.0, 140.0])
        rays = np.column_stack(
            (
                np.sin(theta),
                np.zeros_like(theta),
                np.cos(theta),
            )
        )
        _, _, valid, _ = project_unit_rays_to_fisheye(
            rays,
            calibration,
            200,
            100,
        )
        np.testing.assert_array_equal(valid, [True, False, False])

    def test_perspective_size_fov_and_orientation(self):
        panorama = longitude_panorama()
        forward = render_perspective(panorama, OrientationState.identity(), 101, 51, 90)
        turned = OrientationState.identity().rotate_local(yaw_delta_deg=90)
        right = render_perspective(panorama, turned, 101, 51, 90)
        self.assertEqual(forward.shape, (51, 101, 3))
        self.assertFalse(np.array_equal(forward, right))
        self.assertGreater(int(right[25, 50, 0]), int(forward[25, 50, 0]))

    def test_perspective_horizontal_wrap_does_not_create_black_seam(self):
        panorama = longitude_panorama()
        backward = OrientationState.identity().rotate_local(yaw_delta_deg=180)
        output = render_perspective(panorama, backward, 5, 5, 20)
        self.assertGreater(int(output[2, 2].sum()), 0)
        self.assertFalse(np.any(np.all(output == 0, axis=2)))

    def test_stereographic_horizontal_wrap_has_no_black_meridian(self):
        panorama = longitude_panorama(width=360, height=180)
        orientation = OrientationState.identity().rotate_local(yaw_delta_deg=195)
        output = render_stereographic(panorama, orientation, 320, 180, 150)
        self.assertFalse(np.any(np.all(output == 0, axis=2)))

    def test_projection_map_is_reused_across_video_frames(self):
        panorama = longitude_panorama(width=362, height=181)
        orientation = OrientationState.identity()
        with mock.patch(
            "rpi360.common.rendering.unit_rays_to_equirectangular_map",
            wraps=__import__(
                "rpi360.common.rendering",
                fromlist=["unit_rays_to_equirectangular_map"],
            ).unit_rays_to_equirectangular_map,
        ) as map_builder:
            first = render_perspective(panorama, orientation, 77, 39, 91)
            second = render_perspective(panorama.copy(), orientation, 77, 39, 91)
        self.assertEqual(map_builder.call_count, 1)
        np.testing.assert_array_equal(first, second)

    def test_stereographic_matches_mapper_rectangular_projection(self):
        panorama = longitude_panorama()
        output = render_stereographic(
            panorama, OrientationState.identity(), 100, 80, 150.0
        )
        self.assertEqual(output.shape, (80, 100, 3))
        self.assertGreater(int(output[0, 0].sum()), 0)
        self.assertGreater(int(output[40, 50].sum()), 0)
        rays = stereographic_pixels_to_unit_rays(100, 80, 150.0)
        np.testing.assert_allclose(rays[40, 50], [0.0, 0.0, 1.0])

    def test_mapper_blend_uses_camera0_center_and_camera1_sides(self):
        camera0 = np.full((4, 360, 3), (10, 20, 30), dtype=np.uint8)
        camera1 = np.full((4, 360, 3), (200, 210, 220), dtype=np.uint8)
        blended = blend_equirectangular_mapper(camera0, camera1, 10)
        np.testing.assert_array_equal(blended[:, 0], camera1[:, 0])
        np.testing.assert_array_equal(blended[:, 180], camera0[:, 180])
        np.testing.assert_array_equal(blended[:, 359], camera1[:, 359])

    def test_render_session_reuses_and_invalidates_stage_one(self):
        session = RenderSession(
            self.calibration,
            default_equirectangular_width=160,
            default_equirectangular_height=80,
        )
        session.set_frames(self.frame0, self.frame1)
        view = ViewConfig("perspective", 80, 40)
        orientation = OrientationState.identity()
        first = session.render(orientation, view).image
        orientation.rotate_local(yaw_delta_deg=120)
        second = session.render(orientation, view).image
        self.assertEqual(session.stitch_count, 1)
        self.assertFalse(np.array_equal(first, second))
        session.set_frames(self.frame0, self.frame1)
        session.render(orientation, view)
        self.assertEqual(session.stitch_count, 2)


if __name__ == "__main__":
    unittest.main()
