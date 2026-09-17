# Persistent preview recovery — 2026-09-17

The reported failure was reproduced: neither 5173 nor 8765 had a listener, and
Chrome showed `ERR_CONNECTION_REFUSED`. The previous launcher tied both children
to a temporary terminal process; its successful startup did not establish a
persistent service.

## Changed lifetime

On macOS, `make preview` installs two independent user LaunchAgents. The built
workbench and server are copied to a versioned Application Support directory;
SSH runs with a dedicated key. Both have KeepAlive and RunAtLoad enabled, with a
10-second restart throttle for repeated failures. The CLI exits after readiness
checks. The workbench does not shut down when SSH or the Pi is unavailable.

No password is stored. The Pi public-key entry constrains TCP forwarding to
127.0.0.1:8765 and disables shell/PTY/agent/X11 access. Existing SSH keys and Pi
recordings were preserved. This change did not restart the Pi camera service.

## Executed on the user's Mac

| Check | Result |
| --- | --- |
| Installer lifetime | `make preview CAMERA=henry@raspberrypi` completed with exit 0. Both service processes had PPID 1 after the invoking terminal process exited. |
| Workbench process failure | Sent SIGKILL to the observed managed PID 45670. launchd started PID 46049; `/healthz` recovered in approximately 0.29 seconds. |
| SSH process failure | Sent SIGKILL to managed PID 45950. launchd started PID 46053; proxied Pi `/v1/info` recovered in approximately 0.32 seconds. Workbench health stayed HTTP 200 throughout polling. |
| Longer camera outage | Unloaded the tunnel job. `/api/v1/info` returned 502 while `/healthz` and the page stayed available. Reloaded Chrome during the outage; sample viewing remained available. |
| Reconnection | Reloaded the tunnel job. The existing browser tab changed to Camera connected without manual reconnect or credential entry, then opened real Pi video showing `LIVE · Synced`. |
| Version switch / failed update | An update exposed launchd’s asynchronous unload; the installer now waits for job removal before bootstrap. A new real build then activated successfully. An injected server that exits 42 failed readiness, restored the previous job, waited for HTTP 200, and preserved the current release pointer. |
| Repeated start | Rebuilt the identical snapshot and reused the jobs, without a new password or duplicate listeners. |
| Key restrictions | A remote `true` command returned 1 under the forced command. Forwarding to Pi port 22 and creating an external remote listener were rejected by sshd. |
| Automated coverage | 12 existing Web SDK/media tests and 7 new HTTP integration tests passed. New coverage exercises outage/recovery, both API URL forms, byte ranges/HEAD/WASM, Origin/Host rejection and filesystem traversal/symlink rejection and missing-build health reporting and external-link document navigation. |
| Build | TypeScript and production Web build passed. Node syntax, shell syntax and diff checks passed. |

Recovery times are observations from these two injected failures, not a maximum
recovery guarantee. Login startup is configured; logout/reboot and physical
sleep/wake were not performed during the user's session. A sleeping or powered-off
Mac cannot serve localhost, and live video still needs the Pi and LAN.

The new persistent path is macOS-specific. Other platforms retain the explicit
foreground launcher. `make preview-stop` removes both local jobs and their login
startup entries; it preserves application data and the Pi authorization entry.
