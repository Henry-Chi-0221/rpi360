# Device protocol

The executable source of the API is `apps/camera-service/src/rpi360_camera/api.py`;
`schemas/device-api.openapi.yaml` is generated from its routes. Data format v2
and transport `/v1` are independently versioned.

Pairing is allowed once using a locally displayed six-digit code, expires in five
minutes and is rate-limited. The device stores only a SHA-256 token digest. Tokens
are revocable. The first controller owns control; v2 initially supports one
preview connection. Native clients send a Bearer header. Browser Origin values
must match the service or an explicitly allowed origin.

Record start/stop commands carry a request ID. Responses are persisted to support
retrying the same command. Recording lifecycle does not depend on an open WebRTC
connection. Finished files support HTTP Range and strong checksum ETags.

Preview signaling uses a complete SDP offer/answer (ICE gathering before POST).
One H.264 stream contains both complete fisheyes side by side. Each half is
720×540 in the interoperable 1440×540 baseline H.264 profile. No stitch, FOV crop, or orientation transform is applied on
the camera. A lossy `frames` DataChannel provides pair IDs and sensor timestamps;
its arrival order never determines lens pairing. The image itself is already a
complete pair. SDP codec capability negotiation does not certify every resolution.

Network listening requires TLS. For local development, bind the Pi service to
loopback and use an SSH tunnel plus Vite's same-origin `/api` proxy. Production
may serve the built Web workspace from the same trusted HTTPS origin. Do not
turn off certificate checks or browser security to connect. Chrome LAN permission
is a client/browser interaction to validate for each deployed origin.
