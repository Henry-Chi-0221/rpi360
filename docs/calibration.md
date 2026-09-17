# Calibration principles

> Legacy v1 reference. For the current architecture and migration, see [v2 migration](migration/v2.md) and [validation status](validation/status.md).

RPI360 uses one `calibration-result.json` throughout the camera's life. The
file is updated in place by two independent stages.

## 1. Camera intrinsics

Each fisheye camera has its own intrinsic matrix `K` and four OpenCV fisheye
distortion coefficients `D`. The interactive checkerboard workflow accepts a
sample only after:

- the image has remained stable for the configured number of frames;
- the checkerboard is detected at a useful position and scale;
- the sample increases image coverage;
- the current fisheye solution remains below the reprojection-error limit.

Re-running this stage replaces both cameras' intrinsics and intentionally
invalidates the previous rig rotation. Live viewing and recording remain
disabled until stage 2 is completed again.

## 2. Rig rotation

The production path records both fisheye streams first. Both cameras and
encoders are then closed before feature processing begins. This avoids running
two cameras, two encoders, two remaps, and SIFT at the same time on the Pi.

For every stable candidate:

1. `K` and `D` remap both fisheye frames independently to equirectangular maps.
2. SIFT features are detected inside the valid overlap.
3. Mutual ratio-tested descriptor matches are converted to unit rays.
4. Spherical RANSAC rejects inconsistent matches by angular error.
5. Kabsch/SVD refines the camera 1 to camera 0 rotation on all accepted inliers.
6. Keypoint count, match count, inlier ratio, angular error, and equirectangular
   reprojection error decide whether the sample is retained.

The matrix definition is fixed:

```text
ray_cam0 = R_cam1_to_cam0 @ ray_cam1
```

There is no comparison against an older rotation in the acceptance rules.

## Example calibration

[`calibration/rpi5-dual-imx219-example.json`](../calibration/rpi5-dual-imx219-example.json)
contains the measured 1640 x 1232, 210-degree FOV calibration used for the
included samples. It includes the exact K/D/R values and compact quality
metrics but no local paths or capture history.

It is valid only for that physical camera assembly. Do not use it as a shortcut
for a different rig.
