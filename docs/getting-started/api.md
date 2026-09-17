# Small APIs, clear responsibilities

These are workspace packages in this alpha, not published npm/PyPI releases.
The examples use the same camera API and renderer as the workbench.

## Live VR in TypeScript

Build the workspace with `pnpm install && pnpm wasm`, run
`make preview CAMERA=user@raspberrypi.local`, and follow the [camera connection guide](camera.md). The runnable example is at
<http://localhost:5173/api-example.html>; its source is
[live-example.ts](../../apps/web/src/live-example.ts).
Close the workbench's preview first. Only one viewer is supported at a time.
The standard SSH connection needs no application credentials.

```ts
import { DeviceClient, LiveViewer } from "@rpi360/web-sdk";

const camera = new DeviceClient("/api");
const viewer = await LiveViewer.connect(canvas, camera);

viewer.setView({ yaw: 45, pitch: -10, fov: 100 });
viewer.setView({ projection: "stereographic", pitch: -90, fov: 270 });
// When leaving this view:
await viewer.close(); // releases preview; an active recording continues
```

`canvas` is an HTML canvas with nonzero width/height. Await `LiveViewer.connect()` before
calling `setView()`. Angles are degrees and `fov` is **horizontal**; omitted
values retain their previous settings. Equirectangular projection ignores FOV.
`LiveViewer` handles calibration loading, WebRTC, decoding, texture updates and
GPU cleanup. It does not own your UI, recording lifetime or access policy.
Pass `onError` and `onDiagnostics` in the third argument to display runtime state.

Use `Renderer`, `orientation()`, `evaluate()` and the media adapters directly for
an editor or custom player. `DeviceClient.request()` exposes the full
[device protocol](../protocols/device.md) without duplicating HTTP code.

## Record with Python

From the repository root, run `uv sync` and use `uv run python`.
Keep the background preview service running. The following example is also available as
`uv run python examples/python/record_clip.py`.

```python
from time import sleep
from rpi360.client import DeviceClient

camera = DeviceClient("http://127.0.0.1:8765")
camera.start_capture()
camera.wait_for_sync(timeout=15)
camera.start_recording()
try:
    sleep(10)
finally:
    recording = camera.stop_recording()
print(recording["id"], recording["state"])
```

Python and the browser can share the same SSH tunnel. The example accepts
`RPI360_TOKEN` only for an optional direct HTTPS deployment. Never embed a token
in a URL or commit it. Start/stop accept caller-supplied request IDs; reuse an
ID when retrying an uncertain request.

## HTTP without an SDK

After SSH is connected, both diagnostics and device operations work directly:

```sh
curl --fail http://127.0.0.1:8765/v1/info
curl --fail http://127.0.0.1:8765/v1/status
```

| Operation | Endpoint |
| --- | --- |
| Start sensors / read sync state | `POST /v1/capture/start` / `GET /v1/status` |
| Record / finalize | `POST /v1/recordings/start` / `POST /v1/recordings/stop` with `request_id` |
| List recordings | `GET /v1/recordings` |
| Load calibration | `GET /v1/calibration` |
| Negotiate paired preview | `POST /v1/preview-sessions` with WebRTC offer |

Full request/response contracts: [OpenAPI](../../schemas/device-api.openapi.yaml).
For Swift, see [the Apple SDK](../../packages/apple-sdk/README.md).
