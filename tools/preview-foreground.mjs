#!/usr/bin/env node
// Own only processes started here; existing tunnels and workbenches stay running.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

const root = fileURLToPath(new URL("../", import.meta.url));
const camera = process.argv[2];
const children = new Set();
let stopping = false;
function stop(code) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    // pnpm also owns a Vite child; stop the process group, not just pnpm.
    try {
      child.ownsGroup
        ? process.kill(-child.pid, "SIGTERM")
        : child.kill("SIGTERM");
    } catch {}
  }
  process.exitCode = code;
}
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => stop(0));
function start(command, args) {
  // Keep SSH in the foreground session so /dev/tty can prompt for a password.
  const ownsGroup = command !== "ssh";
  const child = spawn(command, args, {
    cwd: root,
    stdio: "inherit",
    detached: ownsGroup,
  });
  child.ownsGroup = ownsGroup;
  children.add(child);
  child.once("error", (error) => {
    console.error(error.message);
    stop(1);
  });
  child.once("exit", (code) => {
    children.delete(child);
    if (!stopping) {
      console.error(`${command} exited (${code}); preview stopped.`);
      stop(1);
    }
  });
}
async function info(url) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(1500) });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}
function checkCamera(value) {
  if (!value || value.name !== "RPI360" || value.api_version !== 1)
    return false;
  if (value.access_mode !== "local")
    throw new Error(
      value.access_mode === "bearer"
        ? "This API uses an advanced HTTPS token deployment. Use its HTTPS address in the workbench."
        : "Update and restart the Pi camera service from this checkout; this older service still requires pairing.",
    );
  return true;
}
async function portFree(port) {
  return new Promise((resolve) => {
    const server = createServer();
    server.once("error", () => resolve(false));
    server.listen(port, "127.0.0.1", () => server.close(() => resolve(true)));
  });
}
async function waitFor(url, milliseconds) {
  const deadline = Date.now() + milliseconds;
  while (!stopping && Date.now() < deadline) {
    if (checkCamera(await info(url))) return;
    await delay(500);
  }
  if (!stopping)
    throw new Error(
      "Camera API did not become ready. Run make camera on the Pi and check the SSH destination.",
    );
}
try {
  if (!camera || camera.startsWith("-") || /\s/.test(camera))
    throw new Error(
      "Usage from the repository: make preview CAMERA=user@raspberrypi.local",
    );
  if (
    !existsSync(root + "node_modules") ||
    !existsSync(root + "packages/web-sdk/wasm/rpi360_render_bg.wasm")
  )
    throw new Error(
      "Complete the one-time Web setup first: pnpm install && pnpm wasm (see README prerequisites).",
    );
  const api = "http://127.0.0.1:8765/v1/info";
  if (checkCamera(await info(api))) {
    console.log(
      "Reusing the camera API on port 8765. To change cameras, close its existing tunnel first.",
    );
  } else {
    if (!(await portFree(8765)))
      throw new Error(
        "Port 8765 is occupied but the camera API is unavailable. Check the existing tunnel and Pi service; no process was stopped.",
      );
    console.log(
      `Connecting to ${camera}. Enter your normal SSH password if requested.`,
    );
    start("ssh", [
      "-o",
      "ExitOnForwardFailure=yes",
      "-o",
      "ServerAliveInterval=30",
      "-o",
      "ServerAliveCountMax=6",
      "-N",
      "-L127.0.0.1:8765:127.0.0.1:8765",
      camera,
    ]);
    await waitFor(api, 120000);
  }
  if (!stopping) {
    const proxy = "http://localhost:5173/api/v1/info";
    if (checkCamera(await info(proxy)))
      console.log("Reusing the workbench on port 5173.");
    else {
      if (!(await portFree(5173)))
        throw new Error(
          "Port 5173 is occupied by another or outdated app. Close it before starting the workbench.",
        );
      start("pnpm", ["dev"]);
      await waitFor(proxy, 30000);
    }
    if (!stopping) {
      console.log(
        "Open http://localhost:5173 → Camera → Open live preview. No pairing code is needed.",
      );
      console.log(
        "Keep Mac and Pi on the same LAN; WebRTC video uses direct UDP.",
      );
      console.log(
        children.size
          ? "Keep this terminal open. Ctrl+C closes only the processes started here; Pi recording continues."
          : "Both services were already running. Keep their original terminals open.",
      );
    }
  }
} catch (error) {
  console.error(error.message);
  stop(1);
}
