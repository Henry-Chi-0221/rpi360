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
Do not expose the loopback API directly on an external interface.

The optional `make ipad` gateway explicitly trusts devices on the camera's
configured IPv4 LAN subnet. It serves the Web app and proxies the loopback API
through HTTPS, with hostname, peer-subnet and browser-origin checks before
forwarding any request. It removes forwarded identity headers before reaching
the local API. This mode provides shared LAN access, not per-user authentication.
The HTTP bootstrap port serves only setup instructions and the public CA
certificate. Private CA keys stay in the user's private application directory;
verify the Pi's certificate fingerprint before installing it on an iPad.
Do not forward these services from the public internet or put an untrusted proxy
in front of them. Keep the gateway's CA data private and preserve it across updates.

Deployments requiring restricted access use trusted HTTPS plus an operator-managed bearer
token file (0600, at least 32 ASCII characters; generate it cryptographically).
The token is never printed or persisted by the Web client. Rotate the file and
restart the service to replace it after finalizing recording. Allow only trusted
Web origins. Tokens, personal calibration, recordings and logs belong outside Git.

Downloads are confined to completed bundle members. No telemetry or automatic
cloud upload is implemented. Closing the browser or tunnel does not stop an
active recording; the camera service owns its lifetime.
