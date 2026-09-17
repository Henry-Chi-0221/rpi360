# Security

Report vulnerabilities privately using the repository's security reporting
facilities when available; do not put credentials or personal recordings in
public issues. Keep the camera OS updated. This is a v2 alpha, not a certified
internet-facing service.

Default access uses SSH. The API binds to loopback and requires both a loopback
peer and a localhost/loopback Host header. It does not trust forwarded peer
headers. Browser origins are checked. Users and programs with access to the
camera host or forwarded local port can control recording and download media;
use a trusted local computer. There is no pairing code or browser credential.

On macOS, persistent preview adds a dedicated SSH key scoped to Pi loopback port
8765 with a forced failing command and restricted SSH options. The private key
is stored with mode 0600 under the user's RPI360 application data. Passwords are
not stored. Revoke the public key on the Pi to remove this machine's access;
stopping local LaunchAgents alone does not revoke it.
Do not expose or reverse-proxy this local mode on an external interface.

Direct LAN deployments require trusted HTTPS plus an operator-managed bearer
token file (0600, at least 32 ASCII characters; generate it cryptographically).
The token is never printed or persisted by the Web client. Rotate the file and
restart the service to replace it after finalizing recording. Allow only trusted
Web origins. Tokens, personal calibration, recordings and logs belong outside Git.

Downloads are confined to completed bundle members. No telemetry or automatic
cloud upload is implemented. Closing the browser or tunnel does not stop an
active recording; the camera service owns its lifetime.
