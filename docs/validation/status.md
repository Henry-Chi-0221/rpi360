# v2 validation status

This report distinguishes executed checks from release targets. Status applies to
the development implementation, not a published stable release.

## Executed

- Baseline: GitHub main `fb8de0404209186b6904fed889f79ed6a72e4037`; all 69 original
  Python tests passed before migration. Pi's uncommitted 0.2.0 deployment and
  calibration were preserved separately; six original MP4 hashes were verified.
- Pi short integration: dual 1640×1232 H.264 recording plus paired-preview encoding
  for approximately 15 seconds; 450 recorded frames per camera. Sensor pair
  delta p95 was approximately 49 µs. Source PTS and per-track offsets were retained.
- LAN WebRTC: a real aiortc receiver on the Mac received approximately 30 fps at
  the beginning of concurrent recording. An attempted 60-minute run was stopped
  after sustained performance degraded. This did **not** pass the endurance gate.
- Browser: Chrome loaded the shared WASM/wgpu renderer, reframed included source
  images, and exported an eight-second 1280×720 H.264 MP4 locally. ffprobe confirmed
  30 fps output and 8.000 seconds. No worker was used for that export.
- Native: eight demo recipes rendered successfully; each output was decoded and
  verified as 240 frames at 30 fps. Contact-sheet inspection confirmed no embedded
  text and correct output aspect ratios.
- Geometry: 1024 seeded rays compared between the legacy Python equations, native
  Rust C ABI and WASM, below the half-source-pixel tolerance. Project pose/spin
  and source-time parity checks passed.
- Swift: the SDK module compiled on this Mac; a command-line smoke executable
  completed 1000 allocate/evaluate/free cycles. XCTest was unavailable in the
  installed Command Line Tools. This is not iPhone/iPad certification.
- Focused tests cover VFR/common-clock reconstruction, sensor-clock discontinuity,
  retained failed recordings, API authorization/origin rejection, idempotency,
  revocation, Range downloads, project and calibration schemas.

## Additional executed integration checks

Local suite: **82 Python tests, 3 Rust tests, and 7 Web SDK contract tests passed**.
TypeScript checking, Vite production build and Ruff checks passed.

- After bounded recording I/O was added, a 20-second Pi/Mac recording + WebRTC run
  finalized both tracks with **607 frames each**. Storage queue peak was four
  packets; observed sensor-pair p95 was **37 µs**. The receiver obtained 563 preview
  frames over approximately 20.047 seconds. These are short-run observations.
- Chrome successfully received the **1440×540** paired H.264 track and displayed
  a reprojected live camera view. Yaw changed locally and the original paired
  fisheye view was selectable. Codec negotiation now has a regression test using
  an offer containing VP8 before H.264.
- Chrome controlled start/stop of a real Pi recording and downloaded a 31 MB
  bundle through Range requests into OPFS. Both source files passed SHA-256 checks
  and decoded locally with their recorded clock offsets.
- Chrome exported **1440×720 / 30 fps / 240 frames** with recognized spherical
  equirectangular metadata, as verified independently with ffprobe.
- Recovery tests truncate a final media fragment and its index; complete earlier
  fragments are copied to a new bundle. All original file SHA-256 values remain
  unchanged. A simulated checksum failure preserves media and closes handles.
- ZIP tests use Python's independent standard ZIP writer, including ZIP64;
  normal/ZIP64 reads and traversal/collision/truncation rejection pass.
- The Swift GPU adapter rendered a 320×180 RGBA fixture through wgpu/Metal;
  all **230,400 output bytes** matched the native Rust renderer exactly. Reproduce
  with `uv run --no-sync python tools/diagnostics/verify_swift_gpu.py` after building
  the native renderer and Apple SDK.
- With the Pi service stopped, Chrome reopened the downloaded OPFS bundle and
  completed its 15-second local reframe export. A persistent download link remains
  available when the browser blocks automatic downloads.
- A macOS ARM64 Python wheel was built, installed into an independent environment,
  and loaded its packaged C ABI successfully from outside the checkout.

## Clean-build verification

GitHub Actions on commit `0edb7625` passed both Python 3.11/3.13 contract jobs,
including the full 82-test Python suite, Rust tests, native/WASM parity, wheel
build and schema regeneration. The Apple job built macOS ARM64, iOS ARM64 and
iOS Simulator ARM64 libraries, passed two Swift XCTest cases and the C ABI smoke
executable. This extends compilation coverage; physical Apple devices remain
unvalidated. The initial Web job exposed a missing pnpm esbuild allow-list entry;
the explicit package allow-list is corrected in the following commit.

The deployment installer also completed on the actual Pi in a new release
folder. Its independent virtual environment loaded Picamera2/PyAV, started the
API, paired a test client, returned authenticated status and stopped. This smoke
test acquired no camera and did not activate or overwrite existing deployments.
It does not validate version rollback or sustained capture.

## Preview profile adjustment

The original 1640×616 preview uses 4,017 H.264 macroblocks per frame, exceeding
Level 3.1's 3,600 macroblock limit. The interoperable preview profile is now
1440×540 (720×540 per complete lens), baseline Level 3.1. Source recording remains
1640×1232 per lens. Neither camera field of view is cropped. See Chromium's
[H.264 level table](https://chromium.googlesource.com/chromium/src/+/787f41564/media/video/h264_level_limits.cc).

## Remaining release gates

A stable release requires the actual long-duration recording+preview retention
measurement, physical power-cut results, end-to-end latency measurement,
weak-network/background/resume tests, Safari/WebKit coverage, full iOS SDK/device
validation, broader clean-install artifacts and version-switch rollback validation. Automated
legacy file-picker import was blocked by the browser extension’s file-URL permission;
API-downloaded bundle import was exercised instead. Neither is a Safari result.
Do not convert an unrun item into a checkmark or infer a 60-minute pass from a short
sample. Detailed results from additional checks should be added here as executed.

The sustained Pi run reached 85.6°C with throttling. This failed endurance result
is retained as measurement evidence; no long-duration performance claim is made.
