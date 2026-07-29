# Raspberry Pi 5 release checklist

Run this checklist on the assembled two-camera rig before publishing a release.

## Power and cameras

```bash
vcgencmd get_throttled
rpicam-hello --list-cameras
```

- `get_throttled` is `0x0`.
- Both IMX219 cameras appear and their logical order is correct.
- Active cooling is running.

## Calibration

- Print scale verified against the 100 mm reference line.
- Intrinsic UI completes camera 0 and camera 1.
- The resulting JSON is `intrinsics_complete` with no rig rotation.
- Rig capture records 30 seconds without camera errors.
- Both cameras and encoders close before SIFT processing begins.
- Twenty samples pass the documented gates.
- The same JSON becomes `complete`.
- Re-running with `--resume --work-dir ...` updates the rig result without
  reopening cameras.

## Live and record

- Keys 1 through 8 show all projections and intermediate stages.
- BGR colors match the real scene.
- Pause/resume returns to the latest live pair.
- A 60-second recording finalizes after Ctrl-C.
- `rpi360 inspect` reports H.264 track IDs 1 and 2 and both metadata tags.
- MP4 playback matches live rendering for the same camera pair and calibration.

## Final power check

```bash
vcgencmd get_throttled
vcgencmd measure_temp
```

Do not mark the hardware release as validated if under-voltage or throttling
flags are latched.
