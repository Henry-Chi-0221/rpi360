# README and live-preview follow-up — 2026-09-17

This is a focused usability and documentation validation, not a new endurance
or release certification run. Earlier hardware results remain unchanged.

| Check | Result |
| --- | --- |
| Eight README video attachments | GitHub displayed eight native players, each with an 8-second duration and the expected dimensions. Public downloads matched all eight local MP4 SHA-256 values in `demos/videos.manifest.json`. |
| System and projection illustrations | Both SVGs were rasterized and visually checked for clipping, labels and readable layout. |
| Real Pi → Chrome workspace | Started the isolated v2 service, re-established the SSH API tunnel, reconnected with the existing token, and opened live VR preview. UI reported `LIVE · Synced`; an observed sensor pair delta was 21 μs. This is a single displayed observation, not a latency or endurance measurement. |
| Web SDK and example | TypeScript check and production build passed; 10 Web contract/lifecycle tests passed. The additional `api-example.html` page was blocked by this Chrome environment with `ERR_BLOCKED_BY_CLIENT`, so its standalone interactive flow was not browser-validated. The main workspace remained accessible. |
| Python and documentation | Two new device-client tests and four existing public-asset tests passed; Ruff and shell syntax checks passed. |

The service and SSH tunnel remain running for the user's live-preview session.
Stopping the tunnel disconnects control/preview access; it does not itself stop
an active camera recording. The camera service owns recording lifetime.

See [connection instructions](../getting-started/camera.md),
[API examples](../getting-started/api.md), and [overall status](status.md).
