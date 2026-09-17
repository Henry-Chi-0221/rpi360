# Contributing

Use Python 3.11+, Rust, Node.js 22+ and pnpm. Start with `make setup`, then
`make check`. `make web` opens the development server. See the root README for
one-time Rust/WASM tooling installation.

Changes should have a working vertical path and focused validation. Preserve
sensor/media timing, bounded queues, source data on failure, and the calibration
coordinate contract. Rendering changes require native/WASM geometry comparison;
UI changes require a real browser run. Hardware tests are separate and never
silently substituted with mocks. Failed or unrun release gates stay visible.

Do not commit recordings, tokens, personal calibration, runtime logs or generated
binaries. Curated fixtures, small posters and reproducible demo recipes are
allowed. Large demo videos belong in versioned release assets. Never rewrite
history to remove old media as part of ordinary maintenance.

Keep hardware licensing separate. Changes to `hardware/cad` retain its
CERN-OHL-P-2.0 license and modification notices. Media attribution is in
`LICENSE-MEDIA`; application code and documentation use MIT.

For Apple/native pixel parity after building the SDK and native renderer:

```sh
uv run --no-sync python tools/diagnostics/verify_swift_gpu.py
```

See the [repository map](docs/development/repository.md) and
[implementation evidence](docs/development/implementation.md) for component ownership.
