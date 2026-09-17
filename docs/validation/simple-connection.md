# SSH connection without pairing — 2026-09-17

The foreground launcher checks below are historical;
[background-service validation](persistent-preview.md) supersedes its lifetime behavior.

This replaces the earlier alpha pairing flow. It is a focused connection and
access-policy validation, not an endurance or release certification run.

## Executed checks

| Check | Observed result |
| --- | --- |
| Python suite | 87 tests passed, including credential-free controls, persistent command idempotency, Range downloads, removed pairing endpoint, loopback/Host/origin enforcement and optional bearer access. |
| Web suite and build | 12 tests passed; TypeScript and production build passed. A new SDK test verifies no Authorization header and no pairing request. |
| Style and contracts | Ruff and shell syntax checks passed. Device OpenAPI regenerated from executable routes; pair endpoints removed and deployment access modes documented. |
| Swift | SDK build and 1,000 C ABI allocation/evaluate/free smoke cycles passed locally. Local XCTest could not run because this Mac has Command Line Tools without the XCTest module; full Apple tests remain a CI check. |
| Fresh Pi installation | Installed an isolated venv using the documented installer and activation option. Release `ssh-flow-4ccbad56430c` passed camera-package imports and was launched through `make camera`, using the existing separate data directory and calibration. |
| Fresh local launch | `make preview CAMERA=henry@raspberrypi` started SSH with the normal password prompt and started Vite when it was absent. It printed the ready URL after the API proxy responded. |
| Repeated launch | Reused the working API and workbench without a second SSH prompt or port-bind error. |
| Shutdown | Ctrl+C closed both owned local listeners (8765 and 5173). Restart through the same command succeeded. Existing-service reuse did not stop those services. |
| New browser tab | Automatically connected, listed the four existing recordings and displayed real Pi `LIVE · Synced` video after Camera → Open live preview. No code or token was entered. One displayed sensor-pair delta was 26 μs; this is not a latency/endurance statistic. |
| Real API access | curl and the Python client accessed status without Authorization. Invalid Origin and Host requests each returned 403. |

The previous camera service was stopped gracefully after confirming no active
recording. Existing source recordings, calibration and prototypes were left
intact. The old authorized-client file is ignored, not overwritten. The Web
application removes its obsolete saved token keys; it stores no new credentials
for the SSH workflow.

A working SSH/workbench session and live preview were restored for the user.
Only one video viewer is supported; controls no longer require exclusive
controller registration. Pi recording lifetime remains independent of browsers.

README video embeds and projection/system diagrams remain unchanged. The earlier
standalone API example page's browser navigation limitation was not bypassed or
re-tested; the main workbench was used for this end-to-end test.
