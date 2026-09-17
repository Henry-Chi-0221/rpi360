# R360 recording bundle, schema 2

A `.r360` directory contains `manifest.json`, `camera0.mp4`, `camera1.mp4`, two
`cameraN.frames.jsonl` indices, and an optional immutable `calibration.json`.
The manifest lists SHA-256 hashes and byte sizes. It is published through atomic
rename with file/directory fsync. Recordings belong on the configured data disk.

Each source is H.264 in fragmented MP4. Each track starts its media clock at zero;
`media_start_offset_us` maps that PTS back to the shared session clock. The source
index retains media PTS, session PTS, SensorTimestamp, exposure, frame duration,
sequence and synchronization state. Sensor timestamps are decimal strings to
avoid JavaScript integer precision loss. No source timing is reconstructed as
frame index divided by nominal FPS.

The bounded recording queue is independent of preview pairing. Queue exhaustion
is a recording fault, not permission to change recording speed. Preview may drop
old pairs; the recorder stores every packet accepted from each source encoder.
A synchronized pair describes sensor frame timing, not global-shutter exposure.

On success, state becomes `complete`. Failures retain all source bytes and mark
`recovery_required`. `tools/migration/recover_recording.py INPUT OUTPUT` copies
only complete MP4 fragments into a NEW bundle and filters the time indices to
retained packets. It never truncates the original. A partial recovery stays in
`recovering` and is not offered as a completed download.

`archive_recording.py` creates ZIP_STORED archives without transcoding. Editing
projects are separate schema-2 JSON files. Legacy imports preserve container PTS
and explicitly use `sync.method=unknown`; absent exposure and sensor times stay
null. A legacy MP4's timestamp cannot prove physical synchronization.

Fragment duration is approximately one second. The targeted two-second crash
loss bound is a validation target, not a filesystem power-loss guarantee.
