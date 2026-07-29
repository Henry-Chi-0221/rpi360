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
frames at 21 FPS, and encoded at the source camera's native 3280 x 2464
resolution as two H.264 tracks. The complete example calibration is embedded in
both metadata tags.

`showcase/` contains inline animated WebP previews and Full HD H.264 clips for
every effect. The 16:9 showcase clips are 1920 x 1080; the aspect-ratio
animation also demonstrates portrait 1080 x 1920 and square 1440 x 1440 view
configurations. All showcase frames are rendered from the native-size sample
tracks before their README previews are downsampled.

The original approximately 59-second camera files are intentionally not part
of this repository.

Rebuild from authorized source captures:

```bash
python tools/build_sample_media.py \
  /path/to/original_camera_tracks \
  calibration/rpi5-dual-imx219-example.json
python tools/build_showcase_assets.py
```
