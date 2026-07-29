# RPI360 MP4 format

An RPI360 recording is a standard MP4 containing:

- video track ID 1: logical camera 0 H.264;
- video track ID 2: logical camera 1 H.264;
- `rpi360`: compact stream mapping and mathematical calibration;
- `rpi360_calibration_result`: complete calibration JSON and diagnostics.

`Player.mp4()` resolves cameras by track ID, never by stream order. The two
metadata tags must contain identical K/D/R values; disagreement is treated as
corruption and playback is rejected.

Legacy recordings with only the `rpi360` tag remain readable. A compatible
complete result is synthesized in memory, but new recordings always contain
both tags.

## `rpi360` tag

This tag is the minimal stream mapping and mathematical calibration required to
decode and render the recording. Its JSON structure is:

```json
{
  "schema_version": 1,
  "streams": {
    "camera_0": {
      "track_id": 1,
      "width": 3280,
      "height": 2464,
      "fps": 21.0
    },
    "camera_1": {
      "track_id": 2,
      "width": 3280,
      "height": 2464,
      "fps": 21.0
    }
  },
  "calibration": {
    "camera_0": {
      "width": 1640,
      "height": 1232,
      "K": [
        [338.0067, 0.0, 875.3074],
        [0.0, 338.0276, 611.5789],
        [0.0, 0.0, 1.0]
      ],
      "D": [0.0961, -0.0234, -0.0053, 0.0012],
      "fisheye_fov_deg": 210.0
    },
    "camera_1": {
      "width": 1640,
      "height": 1232,
      "K": [
        [336.9645, 0.0, 810.8855],
        [0.0, 336.7994, 623.9854],
        [0.0, 0.0, 1.0]
      ],
      "D": [0.0962, -0.0238, -0.0046, 0.0008],
      "fisheye_fov_deg": 210.0
    },
    "R_cam1_to_cam0": [
      [-0.9997, 0.0065, -0.0239],
      [-0.0049, -0.9980, -0.0634],
      [-0.0243, -0.0633, 0.9977]
    ]
  }
}
```

The numbers above are rounded only for documentation. Stored arrays keep their
full JSON floating-point precision. Calibration width and height describe the
coordinate system in which K was measured; stream width and height describe the
recorded tracks. RPI360 scales K to the decoded frame size before remapping.

`K` is a 3 x 3 intrinsic matrix, `D` contains the four OpenCV fisheye
coefficients, and the rotation definition is:

```text
ray_cam0 = R_cam1_to_cam0 @ ray_cam1
```

## `rpi360_calibration_result` tag

New recordings also store the complete calibration-result document:

```json
{
  "schema_version": 1,
  "calibration_state": "complete",
  "calibration": {
    "camera_0": {"width": 1640, "height": 1232, "K": [], "D": [], "fisheye_fov_deg": 210.0},
    "camera_1": {"width": 1640, "height": 1232, "K": [], "D": [], "fisheye_fov_deg": 210.0},
    "R_cam1_to_cam0": []
  },
  "diagnostics": {
    "intrinsics": {
      "camera_0": {"accepted_sample_count": 0, "mean_reprojection_error_px": 0.0},
      "camera_1": {"accepted_sample_count": 0, "mean_reprojection_error_px": 0.0}
    },
    "rig": {
      "feature_detector": "SIFT",
      "raw_matches": 0,
      "inlier_count": 0,
      "inlier_ratio": 0.0,
      "rmse_inlier_reprojection_error_px": 0.0
    }
  }
}
```

The empty arrays and zero diagnostics above abbreviate variable-length values;
they are not a valid completed calibration. The real tag repeats the full K,
D, and R values from `rpi360` and includes all diagnostics saved by both
calibration stages. Playback rejects the MP4 if the two tags disagree on K/D/R.

Use:

```bash
rpi360 inspect assets/samples/lake.r360.mp4
```

`inspect` prints both the concise tag and the complete embedded calibration
result, so it is the authoritative way to view every stored field without
documentation abbreviations.

The MP4 stores source fisheye tracks, not an exported panorama. Projection and
view direction remain selectable at playback time.
