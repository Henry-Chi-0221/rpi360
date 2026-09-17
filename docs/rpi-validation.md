# Raspberry Pi 5 release checklist

> Legacy v1 reference. For the current architecture and migration, see [v2 migration](migration/v2.md) and [validation status](validation/status.md).

Run this checklist on the assembled two-camera rig before publishing a release.

## Cameras and storage

```bash
rpicam-hello --list-cameras
```

- Both IMX219 cameras appear and their logical order is correct.
- The recording destination has enough free storage.
- The enclosure hardware and custom power-bank mount cannot shift the lenses.

## Calibration

- Print scale verified by measuring four adjacent 25 mm squares as 100 mm.
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

## Final playback check

- Copy the recording to the playback machine.
- Confirm all keys 1 through 8 and the three aspect-ratio examples.
- Compare the MP4 view against the live view with the same orientation and FOV.
