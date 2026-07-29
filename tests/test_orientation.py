import unittest

import numpy as np

from rpi360.common.types import (
    OrientationState,
    rotation_matrix_from_euler,
    validate_rotation_matrix,
)


class OrientationStateTests(unittest.TestCase):
    def test_identity_and_single_local_yaw(self):
        orientation = OrientationState.identity()
        np.testing.assert_allclose(orientation.rotation_matrix, np.eye(3))
        orientation.rotate_local(yaw_delta_deg=90)
        forward = np.array([0.0, 0.0, 1.0]) @ orientation.rotation_matrix
        np.testing.assert_allclose(forward, [1.0, 0.0, 0.0], atol=1e-12)

    def test_local_updates_accumulate_from_current_orientation(self):
        orientation = OrientationState.identity()
        orientation.rotate_local(yaw_delta_deg=30)
        orientation.rotate_local(pitch_delta_deg=-10)
        expected = rotation_matrix_from_euler(0, -10, 0) @ rotation_matrix_from_euler(
            30, 0, 0
        )
        np.testing.assert_allclose(orientation.rotation_matrix, expected, atol=1e-12)

    def test_local_and_world_updates_are_distinct(self):
        local = OrientationState.identity().rotate_local(yaw_delta_deg=35)
        world = local.copy()
        local.rotate_local(pitch_delta_deg=20)
        world.rotate_world(pitch_delta_deg=20)
        self.assertFalse(
            np.allclose(local.rotation_matrix, world.rotation_matrix, atol=1e-8)
        )
        validate_rotation_matrix(local.rotation_matrix)
        validate_rotation_matrix(world.rotation_matrix)

    def test_reset(self):
        orientation = OrientationState.identity().rotate_local(10, 20, 30)
        orientation.reset()
        np.testing.assert_allclose(orientation.rotation_matrix, np.eye(3))

    def test_many_updates_remain_a_proper_rotation(self):
        orientation = OrientationState.identity()
        for _ in range(1000):
            orientation.rotate_local(0.01, -0.02, 0.005)
        self.assertTrue(validate_rotation_matrix(orientation.rotation_matrix))
        self.assertAlmostEqual(
            np.linalg.det(orientation.rotation_matrix), 1.0, places=10
        )


if __name__ == "__main__":
    unittest.main()
