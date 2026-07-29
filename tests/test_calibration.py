import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from rpi360 import (
    DualCameraIntrinsics,
    IntrinsicCalibrationSession,
    RigCalibrationWorkflow,
    RigVideoRecorder,
    VideoRigCalibrationSession,
)
from rpi360.common.metadata import (
    load_calibration_document,
    load_calibration_result,
    update_calibration_document,
)
from rpi360.common.types import (
    CameraCalibration,
    MetadataError,
    PipelineState,
    rotation_matrix_from_euler,
)
from rpi360.rpi.calibration import (
    InteractiveIntrinsicConfig,
    InteractiveRigConfig,
    RigSampleReview,
    RigSampleReviewer,
    calibrate_rig_rotation,
    load_calibration_intrinsics,
    solve_rig_samples,
    update_calibration_intrinsics,
)
from rpi360.rpi.calibration._internals import (
    _equirectangular_points_to_rays,
    _match_equirectangular_features,
    _object_point_template,
    _solve_guided_intrinsics,
)
from rpi360.rpi.calibration.opencv import _fitted_window_size


class CalibrationTests(unittest.TestCase):
    def test_workflow_resume_solves_without_reopening_cameras(self):
        intrinsics = self._sample_intrinsics()
        config = InteractiveRigConfig(
            width=32,
            height=24,
            sample_count=2,
        )
        with tempfile.TemporaryDirectory() as temporary:
            calibration = Path(temporary) / "calibration-result.json"
            work = Path(temporary) / "rig-work"
            work.mkdir()
            (work / "cam0.mp4").touch()
            (work / "cam1.mp4").touch()
            update_calibration_intrinsics(calibration, intrinsics)
            workflow = RigCalibrationWorkflow(
                calibration,
                work_directory=work,
                config=config,
                opencv_threads=1,
            )
            with patch(
                "rpi360.rpi.calibration.workflow.VideoRigCalibrationSession"
            ) as session_class:
                session = session_class.return_value
                session.__enter__.return_value = session
                session.events.return_value = iter(())
                session.save.return_value = calibration
                result = workflow.run(resume=True)

        self.assertEqual(result, calibration)
        session_class.assert_called_once()
        session.save.assert_called_once_with(calibration)

    def test_rig_video_recorder_publishes_portable_capture_directory(self):
        created_devices = []

        class FakeDevice:
            def __init__(self, index, **_values):
                self.index = index
                self.record_size = (32, 24)
                self.output = None
                created_devices.append(self)

            def start(self):
                return self

            def start_recording(self, output):
                self.output = output
                output.write_bytes(b"h264")

            def stop_recording(self):
                pass

            def stop(self):
                pass

        intrinsics = self._sample_intrinsics()
        with tempfile.TemporaryDirectory() as temporary:
            calibration = Path(temporary) / "calibration-result.json"
            output = Path(temporary) / "rig-capture"
            update_calibration_intrinsics(calibration, intrinsics)
            with (
                patch(
                    "rpi360.rpi.calibration.recording.CameraDevice",
                    FakeDevice,
                ),
                patch.object(
                    RigVideoRecorder,
                    "_remux_track",
                    side_effect=lambda source, target: shutil.copy2(source, target),
                ),
            ):
                recorder = RigVideoRecorder(calibration, output)
                recorder.start()
                result = recorder.stop()
                repeated = recorder.stop()
            manifest = json.loads(result.manifest.read_text(encoding="utf-8"))

        self.assertEqual(result, repeated)
        self.assertEqual([device.index for device in created_devices], [0, 1])
        self.assertEqual(manifest["pairing"], "same frame index")
        self.assertEqual(
            manifest["files"]["calibration_result"],
            "calibration-result.json",
        )

    def test_video_rig_session_uses_stable_frame_pairs_and_shared_solver(self):
        class FakeCapture:
            def __init__(self, _path):
                self.position = 0

            def isOpened(self):
                return True

            def get(self, key):
                return {
                    cv2.CAP_PROP_FRAME_COUNT: 12,
                    cv2.CAP_PROP_FRAME_WIDTH: 32,
                    cv2.CAP_PROP_FRAME_HEIGHT: 24,
                    cv2.CAP_PROP_FPS: 10,
                }[key]

            def set(self, key, value):
                self.assert_position_key = key
                self.position = int(value)
                return True

            def read(self):
                frame = np.full(
                    (24, 32, 3),
                    self.position,
                    dtype=np.uint8,
                )
                self.position += 1
                return True, frame

            def release(self):
                pass

        review = RigSampleReview(
            accepted=True,
            reason="quality gates passed",
            diagnostics={
                "keypoints0": 60,
                "keypoints1": 58,
                "matches": 24,
                "inlier_count": 20,
                "maximum_inlier_reprojection_error_px": 1.2,
            },
            equi0=np.zeros((12, 24, 3), dtype=np.uint8),
            equi1=np.zeros((12, 24, 3), dtype=np.uint8),
            points0=np.arange(48, dtype=np.float64).reshape(24, 2),
            points1=np.arange(48, dtype=np.float64).reshape(24, 2),
            inliers=np.ones(24, dtype=bool),
            rotation=np.eye(3),
        )
        intrinsics = self._sample_intrinsics()
        config = InteractiveRigConfig(
            width=32,
            height=24,
            sample_count=2,
            stable_frames=2,
            motion_threshold=3.0,
        )
        with tempfile.TemporaryDirectory() as temporary:
            camera0 = Path(temporary) / "cam0.mp4"
            camera1 = Path(temporary) / "cam1.mp4"
            camera0.touch()
            camera1.touch()
            with (
                patch(
                    "rpi360.rpi.calibration.video.RigSampleReviewer"
                ) as reviewer_class,
                patch(
                    "rpi360.rpi.calibration.video.solve_rig_samples",
                    return_value=(
                        np.eye(3),
                        {
                            "raw_matches": 48,
                            "inlier_count": 40,
                            "rmse_inlier_reprojection_error_px": 1.0,
                        },
                    ),
                ) as solve,
            ):
                reviewer_class.return_value.review.return_value = review
                session = VideoRigCalibrationSession(
                    camera0,
                    camera1,
                    intrinsics,
                    config=config,
                    sample_indices=(0, 5),
                    capture_factory=FakeCapture,
                )
                events = list(session.start().events())

        self.assertEqual(
            [event.status for event in events],
            ["ACCEPT", "ACCEPT", "COMPLETE"],
        )
        self.assertEqual(session.sample_indices, (2, 5))
        self.assertEqual(reviewer_class.return_value.review.call_count, 2)
        self.assertEqual(solve.call_count, 1)
        self.assertEqual(
            session.diagnostics["rig"]["video_sampling"]["pairing"],
            "same frame index",
        )

    def test_headless_session_emits_preview_and_cancels_cleanly(self):
        class FakeCapture:
            def __init__(self, camera_num):
                self.index = camera_num

            def create_preview_configuration(self, **values):
                return values

            def configure(self, _configuration):
                pass

            def start(self):
                pass

            def capture_array(self, _stream):
                return np.full((24, 32, 3), self.index, dtype=np.uint8)

            def stop(self):
                pass

            def close(self):
                pass

        config = InteractiveIntrinsicConfig(
            width=32,
            height=24,
            fps=10,
            target_samples=8,
            coverage_target=0.2,
        )
        session = IntrinsicCalibrationSession(
            camera0=1,
            camera1=2,
            config=config,
            camera_factory=FakeCapture,
        )
        session.start()
        event = session.step()
        self.assertEqual(event.stage, "camera0_intrinsics")
        self.assertEqual(event.preview.shape[1], 32)
        session.cancel()
        self.assertEqual(session.state, PipelineState.CANCELLED)

    def test_intrinsics_create_partial_shared_calibration_result(self):
        intrinsics = self._sample_intrinsics()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "calibration-result.json"
            update_calibration_intrinsics(
                output,
                intrinsics,
                diagnostics={"camera_0": {"opencv_rms_px": 0.2}},
            )
            document = json.loads(output.read_text(encoding="utf-8"))
            restored = load_calibration_intrinsics(output)
            with self.assertRaises(MetadataError):
                load_calibration_result(output)

        self.assertEqual(document["calibration_state"], "intrinsics_complete")
        self.assertEqual(set(document["calibration"]), {"camera_0", "camera_1"})
        self.assertNotIn("R_cam1_to_cam0", document["calibration"])
        self.assertEqual(
            document["calibration"]["camera_0"]["fisheye_fov_deg"],
            210.0,
        )
        np.testing.assert_array_equal(restored.camera0.K, intrinsics.camera0.K)
        np.testing.assert_array_equal(restored.camera1.D, intrinsics.camera1.D)

    def test_rig_preview_window_preserves_four_to_one_aspect_ratio(self):
        self.assertEqual(
            _fitted_window_size(2048, 512),
            (1600, 400),
        )

    def test_new_intrinsics_invalidate_existing_rig_rotation(self):
        intrinsics = self._sample_intrinsics()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "calibration-result.json"
            update_calibration_intrinsics(output, intrinsics)
            document = load_calibration_document(output)
            document["calibration"]["R_cam1_to_cam0"] = np.eye(3).tolist()
            document["calibration_state"] = "complete"
            document["diagnostics"]["rig"] = {"inlier_count": 30}
            update_calibration_document(output, document)
            update_calibration_intrinsics(
                output,
                intrinsics,
                diagnostics={"camera_0": {"accepted_sample_count": 20}},
            )
            updated = load_calibration_document(output)

        self.assertEqual(updated["calibration_state"], "intrinsics_complete")
        self.assertNotIn("R_cam1_to_cam0", updated["calibration"])
        self.assertNotIn("rig", updated["diagnostics"])

    def test_rig_defaults_follow_reference_estimator(self):
        config = InteractiveRigConfig()
        self.assertEqual(
            (config.equirectangular_width, config.equirectangular_height),
            (5152, 2576),
        )
        self.assertEqual(config.feature_scale, 1.0)
        self.assertEqual(config.ransac_threshold_deg, 0.4)
        self.assertEqual(config.sample_ransac_iterations, 5000)
        self.assertEqual(config.maximum_sample_reprojection_error_px, 8.0)

    def test_rig_sample_reviewer_rejects_insufficient_features(self):
        config = InteractiveRigConfig(
            width=32,
            height=24,
            sample_count=2,
            equirectangular_width=32,
            equirectangular_height=24,
            minimum_keypoints_per_camera=20,
        )
        reviewer = RigSampleReviewer(
            self._sample_intrinsics().camera0,
            self._sample_intrinsics().camera1,
            config,
        )
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        geometry = (
            np.zeros((24, 32), dtype=np.float32),
            np.zeros((24, 32), dtype=np.float32),
            np.full((24, 32), 255, dtype=np.uint8),
        )
        points = np.array([[4.0, 8.0], [8.0, 8.0], [12.0, 8.0], [16.0, 8.0]])
        with (
            patch(
                "rpi360.rpi.calibration.core._single_camera_equirectangular_geometry",
                return_value=geometry,
            ),
            patch(
                "rpi360.rpi.calibration.core._remap_single_camera_equirectangular",
                return_value=(frame, geometry[2]),
            ),
            patch(
                "rpi360.rpi.calibration.core._match_equirectangular_features",
                return_value=(
                    points,
                    points,
                    {"keypoints0": 8, "keypoints1": 9, "matches": 4},
                ),
            ),
        ):
            review = reviewer.review(frame, frame)

        self.assertFalse(review.accepted)
        self.assertIn("not enough SIFT keypoints", review.reason)

    def test_rig_sample_reviewer_enforces_pixel_reprojection_threshold(self):
        config = InteractiveRigConfig(
            width=32,
            height=24,
            sample_count=2,
            equirectangular_width=32,
            equirectangular_height=24,
            minimum_keypoints_per_camera=4,
            minimum_matches_per_sample=4,
            minimum_sample_inliers=4,
            minimum_sample_inlier_ratio=1.0,
            maximum_sample_reprojection_error_px=0.5,
        )
        intrinsics = self._sample_intrinsics()
        reviewer = RigSampleReviewer(
            intrinsics.camera0,
            intrinsics.camera1,
            config,
        )
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        geometry = (
            np.zeros((24, 32), dtype=np.float32),
            np.zeros((24, 32), dtype=np.float32),
            np.full((24, 32), 255, dtype=np.uint8),
        )
        points1 = np.array([[4.0, 8.0], [8.0, 10.0], [12.0, 12.0], [16.0, 14.0]])
        points0 = points1 + np.array([1.0, 0.0])
        with (
            patch(
                "rpi360.rpi.calibration.core._single_camera_equirectangular_geometry",
                return_value=geometry,
            ),
            patch(
                "rpi360.rpi.calibration.core._remap_single_camera_equirectangular",
                return_value=(frame, geometry[2]),
            ),
            patch(
                "rpi360.rpi.calibration.core._match_equirectangular_features",
                return_value=(
                    points0,
                    points1,
                    {"keypoints0": 40, "keypoints1": 40, "matches": 4},
                ),
            ),
            patch(
                "rpi360.rpi.calibration.core.calibrate_rig_rotation",
                return_value=(
                    np.eye(3),
                    np.ones(4, dtype=bool),
                    np.zeros(4),
                ),
            ),
        ):
            review = reviewer.review(frame, frame)

        self.assertFalse(review.accepted)
        self.assertAlmostEqual(
            review.diagnostics["maximum_inlier_reprojection_error_px"],
            1.0,
            places=5,
        )
        self.assertIn("reprojection error", review.reason)

    def test_rig_sample_reviewer_rejects_failed_reference_ransac(self):
        config = InteractiveRigConfig(
            width=32,
            height=24,
            sample_count=2,
            equirectangular_width=32,
            equirectangular_height=24,
            minimum_keypoints_per_camera=4,
            minimum_matches_per_sample=4,
        )
        intrinsics = self._sample_intrinsics()
        reviewer = RigSampleReviewer(
            intrinsics.camera0,
            intrinsics.camera1,
            config,
        )
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        geometry = (
            np.zeros((24, 32), dtype=np.float32),
            np.zeros((24, 32), dtype=np.float32),
            np.full((24, 32), 255, dtype=np.uint8),
        )
        points = np.array([[4.0, 8.0], [8.0, 10.0], [12.0, 12.0], [16.0, 14.0]])
        with (
            patch(
                "rpi360.rpi.calibration.core._single_camera_equirectangular_geometry",
                return_value=geometry,
            ),
            patch(
                "rpi360.rpi.calibration.core._remap_single_camera_equirectangular",
                return_value=(frame, geometry[2]),
            ),
            patch(
                "rpi360.rpi.calibration.core._match_equirectangular_features",
                return_value=(
                    points,
                    points,
                    {"keypoints0": 40, "keypoints1": 40, "matches": 4},
                ),
            ),
            patch(
                "rpi360.rpi.calibration.core.calibrate_rig_rotation",
                side_effect=RuntimeError("RANSAC failed: best inliers=3"),
            ),
        ):
            review = reviewer.review(frame, frame)

        self.assertFalse(review.accepted)
        self.assertIn("RANSAC failed", review.reason)
        self.assertIn("rotation_error", review.diagnostics)

    def test_guided_intrinsic_solver_recovers_known_fisheye(self):
        config = InteractiveIntrinsicConfig(
            width=640,
            height=480,
            checkerboard=(9, 6),
            square_size=0.024,
            target_samples=8,
            coverage_target=0.2,
        )
        objects = _object_point_template(config.checkerboard, config.square_size)
        expected_K = np.array(
            [[210.0, 0.0, 320.0], [0.0, 212.0, 240.0], [0.0, 0.0, 1.0]]
        )
        expected_D = np.array([-0.02, 0.003, -0.0002, 0.00001]).reshape(4, 1)
        poses = [
            ((-0.20, -0.10, 0.05), (-0.10, -0.05, 0.70)),
            ((0.20, -0.10, -0.05), (0.08, -0.03, 0.65)),
            ((-0.15, 0.20, 0.10), (-0.08, 0.05, 0.60)),
            ((0.10, 0.20, -0.10), (0.10, 0.06, 0.75)),
            ((0.00, 0.00, 0.25), (0.00, 0.00, 0.55)),
            ((0.25, 0.05, 0.15), (0.02, -0.08, 0.70)),
            ((-0.20, 0.10, -0.15), (-0.03, 0.08, 0.80)),
            ((0.05, -0.25, 0.20), (0.06, 0.02, 0.62)),
        ]
        corners = [
            cv2.fisheye.projectPoints(
                objects,
                np.asarray(rotation, dtype=np.float64),
                np.asarray(translation, dtype=np.float64),
                expected_K,
                expected_D,
            )[0]
            for rotation, translation in poses
        ]
        result, reason = _solve_guided_intrinsics(corners, config, None)
        self.assertEqual(reason, "")
        self.assertIsNotNone(result)
        np.testing.assert_allclose(result["K"], expected_K, atol=1e-4)
        np.testing.assert_allclose(result["D"], expected_D, atol=1e-4)
        self.assertLess(float(result["per_sample_errors"].max()), 1e-5)

    def test_sift_rotation_pipeline_preserves_cam1_to_cam0_direction(self):
        height, width, shift = 128, 256, 32
        generator = np.random.default_rng(3)
        image0 = generator.integers(0, 256, (height, width, 3), dtype=np.uint8)
        image0 = cv2.GaussianBlur(image0, (3, 3), 0)
        image1 = np.roll(image0, shift, axis=1)
        mask = np.full((height, width), 255, dtype=np.uint8)
        config = InteractiveRigConfig(
            width=width,
            height=height,
            capture_seconds=1,
            sample_count=2,
            equirectangular_width=width,
            equirectangular_height=height,
            feature_scale=1.0,
            nfeatures=2000,
            ratio_threshold=0.8,
            latitude_limit_deg=80,
            mask_erode_pixels=0,
            ransac_iterations=400,
            minimum_inliers=8,
        )
        points0, points1, _ = _match_equirectangular_features(
            image0, image1, mask, mask, config
        )
        rays0 = _equirectangular_points_to_rays(points0, width, height)
        rays1 = _equirectangular_points_to_rays(points1, width, height)
        actual, inliers, _ = calibrate_rig_rotation(
            rays0,
            rays1,
            ransac_threshold_deg=0.5,
            ransac_iterations=400,
        )
        expected = rotation_matrix_from_euler(shift / width * 360.0)
        self.assertGreater(np.count_nonzero(inliers), 100)
        np.testing.assert_allclose(actual, expected, atol=1e-4)

    def test_rig_rotation_recovers_known_geometry_with_outliers(self):
        generator = np.random.default_rng(7)
        rays1 = generator.normal(size=(80, 3))
        rays1 /= np.linalg.norm(rays1, axis=1, keepdims=True)
        expected = rotation_matrix_from_euler(177.0, -1.5, 2.0)
        rays0 = rays1 @ expected.T
        rays0[:8] = generator.normal(size=(8, 3))
        rays0[:8] /= np.linalg.norm(rays0[:8], axis=1, keepdims=True)
        actual, inliers, errors = calibrate_rig_rotation(
            rays0,
            rays1,
            ransac_threshold_deg=0.2,
            ransac_iterations=800,
        )
        np.testing.assert_allclose(actual, expected, atol=1e-8)
        self.assertGreaterEqual(np.count_nonzero(inliers), 72)
        self.assertLess(np.median(errors[inliers]), 1e-5)

    def test_reference_rig_rotation_requires_four_matches(self):
        rays = np.eye(3)
        with self.assertRaisesRegex(ValueError, "at least four"):
            calibrate_rig_rotation(rays, rays)

    def test_final_rig_solve_reuses_accepted_interactive_matches(self):
        intrinsics = self._sample_intrinsics()
        config = InteractiveRigConfig(
            width=32,
            height=24,
            capture_seconds=1,
            sample_count=2,
            equirectangular_width=64,
            equirectangular_height=32,
            ransac_threshold_deg=0.5,
            ransac_iterations=20,
            minimum_inliers=4,
            minimum_inlier_ratio=0.0,
        )
        points1 = np.array(
            [[8.0, 8.0], [20.0, 10.0], [32.0, 16.0], [48.0, 22.0], [56.0, 12.0]]
        )
        points0 = points1.copy()
        points0[:, 0] = (points0[:, 0] + 4.0) % 64.0
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        with patch(
            "rpi360.rpi.calibration.core._single_camera_equirectangular_geometry",
            side_effect=AssertionError("accepted matches must avoid remapping"),
        ):
            _, diagnostics = solve_rig_samples(
                intrinsics.camera0,
                intrinsics.camera1,
                [(frame, frame)],
                [{"elapsed_s": 1.0, "sync_difference_us": 5.0}],
                config,
                matched_points=[
                    (
                        points0,
                        points1,
                        {"keypoints0": 20, "keypoints1": 18, "matches": 5},
                    )
                ],
            )

        self.assertEqual(
            diagnostics["final_match_source"],
            "accepted interactive sample matches",
        )
        self.assertEqual(diagnostics["raw_matches"], 5)

    @staticmethod
    def _sample_intrinsics():
        camera0 = CameraCalibration(
            32,
            24,
            np.array([[12.0, 0.0, 16.0], [0.0, 12.5, 12.0], [0.0, 0.0, 1.0]]),
            np.array([-0.01, 0.001, 0.0, 0.0]),
        )
        camera1 = CameraCalibration(
            32,
            24,
            np.array([[12.2, 0.0, 16.1], [0.0, 12.4, 11.9], [0.0, 0.0, 1.0]]),
            np.array([-0.02, 0.002, 0.0, 0.0]),
        )
        return DualCameraIntrinsics(camera0, camera1)


if __name__ == "__main__":
    unittest.main()
