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

Use:

```bash
rpi360 inspect assets/samples/lake.r360.mp4
```

The MP4 stores source fisheye tracks, not an exported panorama. Projection and
view direction remain selectable at playback time.
