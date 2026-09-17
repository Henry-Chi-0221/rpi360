# Repository map

The camera service has no renderer or GUI dependency. Device clients and media
adapters use the shared core and GPU renderer. Existing Python playback and
calibration code remains available during the v2 transition.

```text
rpi360/
├── README.md
├── Cargo.toml / Cargo.lock / rust-toolchain.toml
├── pyproject.toml / uv.lock / setup.py
├── package.json / pnpm-workspace.yaml / pnpm-lock.yaml
├── Makefile / CONTRIBUTING.md / SECURITY.md / CHANGELOG.md
├── apps/
│   ├── camera-service/src/rpi360_camera/
│   │   ├── capture.py / synchronization.py / settings.py
│   │   ├── recording.py / recovery.py / storage.py
│   │   └── preview.py / api.py / __main__.py
│   ├── web/src/
│   │   ├── App.tsx / main.tsx / style.css
│   │   ├── editor/ / viewer/ / export/
│   │   └── media-contracts.test.ts
│   └── media-worker/src/rpi360_worker/
│       └── api.py / export.py
├── crates/
│   ├── rpi360-core/src/lib.rs
│   ├── rpi360-render/{src,shaders}/
│   └── rpi360-ffi/src/{lib.rs,gpu.rs}
├── packages/
│   ├── python/src/rpi360/
│   │   ├── core/ / client/ / compat/
│   │   └── common/ / playback/ / adapters/ / rpi/calibration/
│   ├── web-sdk/src/
│   │   ├── device/ / renderer/ / types.ts
│   │   └── media/{source,manifest,storage,zip,export,spherical}.ts
│   └── apple-sdk/
│       ├── Package.swift / Sources/RPI360/
│       └── Examples/ / Smoke/ / Tests/
├── schemas/
│   ├── device-api.openapi.yaml / worker-api.openapi.yaml
│   └── {recording,calibration,project}.schema.json
├── demos/{recipes,posters}/ / demos/sources.manifest.json
├── fixtures/legacy-recordings/
├── calibration/                   # Existing public example calibration
├── hardware/{cad,photos}/
├── docs/
│   ├── getting-started/ / architecture/ / protocols/
│   └── development/ / validation/ / migration/ / adr/
├── examples/{calibration,playback}/ # Existing Python transition examples
├── tools/
│   ├── demos/ / migration/ / diagnostics/
│   └── release/
├── deploy/raspberry-pi/{systemd,install.sh,config.example.toml}
├── tests/{contracts,golden,integration,recovery}/
└── .github/{workflows,ISSUE_TEMPLATE}/
```

Modules remain flat while small; directories are introduced when a component
actually needs multiple files. This tree describes existing code, not empty
placeholders for future features.

Build outputs, XCFrameworks, WASM, local recordings, credentials and exports are
excluded from Git. Generate artifacts using the commands in CONTRIBUTING.md.
