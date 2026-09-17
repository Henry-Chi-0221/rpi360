# RPI360 for Swift

The package wraps the shared Rust core and GPU renderer through a C ABI, with a
device API client and AVFoundation frame adapters. It is an integration reference;
it does not include a complete iOS app or a native WebRTC transport.

Build the artifacts from the repository root:

```sh
python3 tools/release/build-apple.py --mac-only
# With full Xcode, the required SDKs and Rust targets installed:
python3 tools/release/build-apple.py
```

See [the core contract](../../docs/architecture/core.md) and the
[recording inspection example](Examples/InspectRecording.swift). The Swift
package consumes the generated XCFramework; do not commit build outputs.

```swift
import Foundation
import RPI360

let camera = DeviceClient(baseURL: URL(string: "https://camera.local")!)
try await camera.pair(code: codeFromPi, name: "My iPad")
let status = try await camera.request("/v1/status")
```

The camera needs a certificate trusted by the device. The development computer's
`localhost` SSH tunnel cannot be used from an iPad. See
[direct HTTPS deployment](../../docs/getting-started/camera.md#trusted-https-deployment).
One paired controller and one live viewer are currently supported. On-device
performance and iPhone/iPad certification remain validation work.
