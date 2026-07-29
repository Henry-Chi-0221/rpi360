# Curated media

Copyright (c) 2026 Henry Chi. Licensed under
[CC BY 4.0](../LICENSE-MEDIA).

The three RPI360 MP4 samples are derived from synchronized camera pairs recorded
with the same physical Raspberry Pi 5 / dual IMX219 rig:

| Public file | Source capture | Use in documentation |
| --- | --- | --- |
| `samples/lake.r360.mp4` | `20260506_160728` | hero and projection comparison |
| `samples/steps.r360.mp4` | `20260506_161921` | tiny-planet effect |
| `samples/waterfront.r360.mp4` | `20260506_164938` | perspective view control |

Each public sample contains only frames 105 through 230, normalized to 126
frames at 21 FPS, scaled to 1640 x 1232, and encoded as two H.264 tracks. The
complete example calibration is embedded in both metadata tags.

The original approximately 59-second camera files are intentionally not part
of this repository.

Rebuild from authorized source captures:

```bash
python tools/build_sample_media.py \
  /path/to/original_camera_tracks \
  calibration/rpi5-dual-imx219-example.json
python tools/build_showcase_assets.py
```
