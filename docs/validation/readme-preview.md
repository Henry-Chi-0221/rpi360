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

## Browser pairing recovery (historical; superseded)

The pairing system described below was subsequently removed at the user’s
request. Current connections use SSH without application credentials; see
[the replacement validation](simple-connection.md).

A later user attempt reached the Pi but received `401: pair this client first`
in a separately opened workspace tab. The original implementation only retained
credentials in session storage, so a healthy SSH tunnel did not authorize that
tab. The fix adds opt-in **Remember this browser**, migrates an existing tab's
credential after successful authentication, and distinguishes a reachable camera
with missing pairing from an unavailable camera.

With the user's consent, the existing authorized tab saved its pairing. The
previously failing tab then connected with a blank code and displayed
`LIVE · Synced`. After the final UI reload, the remember checkbox remained
selected; blank-code reconnection and live preview succeeded again. No Pi
restart, controller reset or recording-file changes were needed. Full browser
restart was not performed during this user's active session.

Thirteen Web tests passed, including three new cases for tab-only isolation,
opt-in migration/new-tab access, removal of stored credentials, opting out and
storage failure preservation. TypeScript and the production Web build passed.
Server-side revocation remains required to invalidate an already-issued token;
clearing browser storage alone is not a server revocation.
