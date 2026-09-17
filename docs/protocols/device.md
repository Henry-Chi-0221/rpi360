# Device protocol

The executable source of the API is `apps/camera-service/src/rpi360_camera/api.py`;
`schemas/device-api.openapi.yaml` is generated from its routes. Data format v2
and transport `/v1` are independently versioned.

Default `access_mode: local` uses SSH authentication. Requests must come from
loopback and address a localhost/loopback Host. Forwarded IP headers are not
trusted. No application credentials are needed; controls are shared. Preview
capacity remains one video viewer. Unapproved browser origins and cross-site
requests without an Origin are rejected.

Optional `access_mode: bearer` uses an operator-configured token from a private
file. All device operations require its Bearer header; `/v1/info` reports the
mode without authentication. Non-loopback listening requires both TLS and this
token. The OpenAPI alternatives describe these two deployment modes; an empty
security requirement only applies to the constrained local mode.

The earlier alpha's `/v1/pair` endpoints and exclusive-controller registry are
removed. Update the service and SDK together. Existing token files are ignored,
not modified; default clients omit Authorization. See the [setup guide](../getting-started/camera.md).

Record start/stop commands carry a request ID. Responses are persisted to support
retrying the same command. Recording lifecycle does not depend on an open WebRTC
connection. Finished files support HTTP Range and strong checksum ETags.

Preview signaling uses a complete SDP offer/answer (ICE gathering before POST).
One H.264 stream contains both complete fisheyes side by side. Each half is
720×540 in the interoperable 1440×540 baseline H.264 profile. No stitch, FOV crop, or orientation transform is applied on
the camera. A lossy `frames` DataChannel provides pair IDs and sensor timestamps;
its arrival order never determines lens pairing. The image itself is already a
complete pair. SDP codec capability negotiation does not certify every resolution.

Network listening requires TLS and a configured API token. For local development, bind the Pi service to
loopback and use an SSH tunnel plus Vite's same-origin `/api` proxy. Production
may serve the built Web workspace from the same trusted HTTPS origin. Do not
turn off certificate checks or browser security to connect. Chrome LAN permission
is a client/browser interaction to validate for each deployed origin.
