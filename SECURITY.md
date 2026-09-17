# Security

Report vulnerabilities privately using the repository's security reporting
facilities when available; do not put device tokens or personal recordings in
public issues. Until a stable v2 release is certified, deploy on trusted local
networks and keep the camera's OS updated.

The service requires TLS for non-loopback listening, rejects unapproved browser
origins, authenticates device operations, and confines downloads to completed
bundle members. Tokens are stored as hashes on the camera. Pairing codes are
short-lived and local. Logs, recordings, personal calibration and credentials
belong in the application data directory, not in Git.

No telemetry or automatic cloud upload is implemented. Revoking a controller
closes preview connections but intentionally does not discard an active recording.
