# v2 implementation and evidence

The accepted architecture separates camera acquisition from client rendering.
This file tracks implementation evidence; it is not a release certification.

Baseline: `fb8de0404209186b6904fed889f79ed6a72e4037`.

## Milestones

| Phase | Implemented evidence | Outstanding acceptance |
|---|---|---|
| P0 | Original Pi code/calibration backup; six source checksums; legacy fixtures | None for the preserved baseline |
| P1 | Versioned schemas/OpenAPI, Rust/WASM/C ABI geometry, shared WGSL renderer | Broader device/backend image matrix |
| P2 | Picamera2 sensor-clock capture, software sync, bounded write queue, fMP4 recovery | 60-minute retention and physical power-cut test |
| P3 | Pairing/revocation, H.264 paired WebRTC, Range transfer, revisioned sensor settings | Weak-network/latency and trusted-HTTPS LAN matrix |
| P4 | Web local import, rendering, keyframes, presets, IndexedDB/OPFS, MP4/360 export | Safari/WebKit and large-file lifecycle matrix |
| P5 | Native worker, legacy adapters/converters, Swift C ABI plus GPU adapter | Full iOS SDK/device certification |
| P6 | Eight recipes rendered from existing originals; clean posters; bilingual product entry | Versioned public media upload with release |
| P7 | Python platform wheel smoke-tested; build/test workflows and release tooling | Endurance, deployment rollback, complete release evidence |

This is an executable alpha implementation. A stable v2 release has not been published.
See [executed validation](../validation/status.md) for exact outcomes and limitations.

## Remaining functional work

The alpha supports the exercised end-to-end workflow. The broader accepted plan
also calls for these additions before a complete production release:

- Network-feedback-driven preview bitrate/resolution adaptation; the current
  fallback responds to encoding load and keeps a bounded latest-pair queue.
- Calibration version management through the device API. Current profiles are
  loaded at service startup, served read-only, and snapshotted into each recording.
- Broader custom time-remap editing, beyond the built-in speed-curve presets.
- Optimized platform texture import; current Web and Swift adapters copy pixels.
- Automated browser lifecycle coverage and public versioned release media.

## Constraints

Keep original recordings and personal calibration outside Git. Do not overwrite
the existing Pi prototypes. Never infer sensor synchronization from frame index,
network arrival time, nominal frame rate, or encoder startup time. Existing
outdoor footage has irregular timestamps and roughly six frames per second;
re-rendering cannot restore missing motion samples.

Publish measured results separately from targets. Apple simulator compilation
does not certify a physical iPhone or iPad. A production release requires the
60-minute capture/preview endurance test and documented recovery results.
