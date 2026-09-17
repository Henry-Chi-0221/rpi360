# Core contract

Rig coordinates are right-handed: +X right, +Y up, -Z forward. Lens coordinates
are +X right, +Y image-down, +Z optical-forward. `camera_to_rig` is a row-major
matrix applied to column vectors. The renderer uses its transpose to project a
rig ray into the lens. Intrinsics belong to the declared calibration resolution;
full-field rescaling scales their image coordinates without changing the lens.

Legacy conversion is deliberately `S * R * mount`, where
`S = diag(1,-1,-1)` and `mount = diag(1,-1,-1)`. Copying the legacy R alone is wrong.
Golden tests compare 1024 rays against the original Python equations and the
same WASM core, with a maximum allowed error below half a source pixel.

Orientation is normalized quaternion `[x,y,z,w]`. Horizontal FOV is the angle
across the output's width; vertical FOV follows aspect ratio. Ordinary quaternion
interpolation takes the shortest arc. `spin_deg` is an independent unwrapped
rotation around the view's forward axis, so a 360-degree roll is not erased.
Keyframes use smoothstep easing unless `linear` is true. Projection changes are
explicit keyframe cuts; do not silently blend incompatible projection models.
Time-remap points map output microseconds to source microseconds. Constant source
time represents a freeze; increasing values represent real playback or speed-up.

The shader applies calibrated fisheye distortion, deterministic overlap feathering,
and per-lens RGB gain. Gains default to unity: automatic photometric calibration
is not implied. Interactive sampling is bilinear; native/browser exports use four
subpixel samples. This deterministic blend cannot remove near-field parallax.

The C ABI returns allocated UTF-8 JSON. Free each result exactly once with
`rpi360_free`. Core requests have no mutable global state. The Rust API is the
reference; Python, WASM and Swift wrappers must not duplicate its mathematics.

The Apple `Renderer` retains the same wgpu context through a C ABI and accepts
paired BGRA CVPixelBuffers or packed RGBA data. The reference adapter copies pixels
and reads back RGBA; direct CVMetalTexture interop remains a performance follow-up.
Build only the Mac reference with `python tools/release/build-apple.py --mac-only`.
Building iOS slices requires the corresponding SDK/toolchain; a Mac pass does not
certify iPhone or iPad operation.
