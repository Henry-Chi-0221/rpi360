# ADR 0001: capture on camera, rendering on clients

Accepted for v2. The Pi owns synchronized sources and reliable recording. A
single paired WebRTC track avoids independent browser video tracks drifting.
Rust defines portable geometry/timeline semantics, and wgpu supplies native and
Web GPU backends. Python remains the hardware/calibration adapter; React owns
interaction. An optional native worker executes the same edit project and shader.

Consequences: codecs and GPU texture import remain platform-specific adapters;
we accept an explicit pixel-copy boundary until zero-copy paths are measured.
A browser must be able to edit and export without a Mac worker. Full application
interfaces never enter the core. No cloud processing is implicit.
