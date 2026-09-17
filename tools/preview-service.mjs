import { spawn, execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  existsSync,
  readFileSync,
  writeFileSync,
  mkdirSync,
  cpSync,
  readdirSync,
  rmSync,
  renameSync,
  symlinkSync,
  realpathSync,
  chmodSync,
} from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

export const labels = {
  web: "io.rpi360.workbench",
  tunnel: "io.rpi360.camera-tunnel",
};
export const xml = (value) =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
export function launchAgent(label, args, log, workingDirectory) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${xml(label)}</string>
<key>ProgramArguments</key><array>${args.map((arg) => `<string>${xml(arg)}</string>`).join("")}</array>
<key>WorkingDirectory</key><string>${xml(workingDirectory)}</string>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>10</integer>
<key>ProcessType</key><string>Background</string>
<key>StandardOutPath</key><string>${xml(log)}</string>
<key>StandardErrorPath</key><string>${xml(log)}</string>
</dict></plist>\n`;
}
export function authorizedKey(publicKey) {
  if (!/^ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\r\n]*)?$/.test(publicKey.trim()))
    throw new Error("Invalid dedicated public key");
  return (
    'restrict,port-forwarding,permitopen="127.0.0.1:8765",permitlisten="127.0.0.1:8765",command="/bin/false" ' +
    publicKey.trim()
  );
}
const quote = (value) => "'" + value.replaceAll("'", "'\\''") + "'";
export function installKeyCommand(publicKey) {
  const line = quote(authorizedKey(publicKey));
  return `umask 077; mkdir -p ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && (grep -qxF -- ${line} ~/.ssh/authorized_keys || printf '%s\\n' ${line} >> ~/.ssh/authorized_keys)`;
}
export function tunnelArgs(camera, key) {
  return [
    "/usr/bin/ssh",
    "-NT",
    "-i",
    key,
    "-o",
    "IdentitiesOnly=yes",
    "-o",
    "IdentityAgent=none",
    "-o",
    "BatchMode=yes",
    "-o",
    "StrictHostKeyChecking=yes",
    "-o",
    "ControlMaster=no",
    "-o",
    "ControlPath=none",
    "-o",
    "ExitOnForwardFailure=yes",
    "-o",
    "ConnectTimeout=5",
    "-o",
    "ServerAliveInterval=10",
    "-o",
    "ServerAliveCountMax=3",
    "-L127.0.0.1:8765:127.0.0.1:8765",
    camera,
  ];
}
async function run(command, args, cwd) {
  await new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, stdio: "inherit" });
    child.on("error", reject);
    child.on("exit", (code) =>
      code === 0 ? resolve() : reject(new Error(`${command} exited (${code})`)),
    );
  });
}
async function json(url) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(1500) });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}
function loaded(label) {
  try {
    return execFileSync(
      "/bin/launchctl",
      ["print", `gui/${process.getuid()}/${label}`],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
    );
  } catch {
    return null;
  }
}
async function bootout(label) {
  if (loaded(label))
    execFileSync("/bin/launchctl", [
      "bootout",
      `gui/${process.getuid()}/${label}`,
    ]);
  // bootout can return while launchd still reports the terminating job.
  for (let attempt = 0; attempt < 100; attempt++) {
    if (!loaded(label)) return;
    await delay(100);
  }
  throw new Error(`Timed out unloading ${label}`);
}
function hashTree(path, hash) {
  for (const entry of readdirSync(path, { withFileTypes: true }).sort((a, b) =>
    a.name.localeCompare(b.name),
  )) {
    hash.update(entry.name);
    if (entry.isDirectory()) hashTree(join(path, entry.name), hash);
    else if (entry.isFile()) hash.update(readFileSync(join(path, entry.name)));
    else throw new Error("Build output must not contain symlinks");
  }
}
export async function managePreview({ root, camera, action = "start" }) {
  const base = join(homedir(), "Library/Application Support/RPI360");
  const agents = join(homedir(), "Library/LaunchAgents");
  const logs = join(homedir(), "Library/Logs/RPI360");
  for (const path of [base, agents, logs])
    mkdirSync(path, { recursive: true, mode: 0o700 });
  const configPath = join(base, "preview.json");
  const config = existsSync(configPath)
    ? JSON.parse(readFileSync(configPath, "utf8"))
    : {};
  const file = (label) => join(agents, label + ".plist");
  if (action === "stop") {
    for (const label of Object.values(labels)) {
      await bootout(label);
      rmSync(file(label), { force: true });
    }
    console.log(
      "Background preview stopped; automatic login startup removed. Pi recording is unaffected.",
    );
    return;
  }
  if (action === "status") {
    for (const [name, label] of Object.entries(labels)) {
      const state = loaded(label),
        pid = state?.match(/\n\s*pid = (\d+)/)?.[1];
      console.log(
        `${name}: ${state ? (state.match(/state = ([^\n]+)/)?.[1] ?? "loaded") : "stopped"}${pid ? " · PID " + pid : ""}`,
      );
    }
    console.log(
      "Workbench:",
      (await json("http://localhost:5173/healthz"))?.name ?? "unavailable",
    );
    console.log(
      "Camera:",
      (await json("http://localhost:5173/api/v1/info"))?.name ??
        "offline/reconnecting",
    );
    console.log("Logs:", logs);
    return;
  }
  if (!["start", "authorize"].includes(action))
    throw new Error("Use start, status, stop or authorize");
  camera ||= config.camera;
  if (camera && (camera.startsWith("-") || /\s/.test(camera)))
    throw new Error("Use a valid SSH destination: user@raspberrypi.local");
  const lock = join(base, "setup.lock");
  if (existsSync(lock)) {
    const pid = Number(readFileSync(lock, "utf8"));
    let alive = true;
    try {
      process.kill(pid, 0);
    } catch {
      alive = false;
    }
    if (alive) throw new Error("Another preview setup is running.");
    rmSync(lock);
  }
  writeFileSync(lock, String(process.pid), { flag: "wx", mode: 0o600 });
  try {
    if (!existsSync(join(root, "packages/web-sdk/wasm/rpi360_render_bg.wasm")))
      throw new Error(
        "Run the one-time README setup: pnpm install && pnpm wasm",
      );
    await run("pnpm", ["build"], root);
    const build = join(root, "apps/web/dist");
    const hash = createHash("sha256");
    hashTree(build, hash);
    hash.update(readFileSync(join(root, "tools/workbench-server.mjs")));
    const release = join(base, "releases", hash.digest("hex").slice(0, 16));
    if (!existsSync(release)) {
      const stage = release + `-${process.pid}.staging`;
      mkdirSync(stage, { recursive: true, mode: 0o700 });
      cpSync(build, join(stage, "web"), { recursive: true });
      cpSync(
        join(root, "tools/workbench-server.mjs"),
        join(stage, "server.mjs"),
      );
      renameSync(stage, release);
    }
    const node =
      ["/opt/homebrew/bin/node", "/usr/local/bin/node"].find(
        (path) => existsSync(path) && realpathSync(path) === process.execPath,
      ) ?? process.execPath;
    async function install(label, args) {
      const contents = launchAgent(
        label,
        args,
        join(logs, label + ".log"),
        base,
      );
      const previous = existsSync(file(label))
        ? readFileSync(file(label), "utf8")
        : null;
      const unchanged = previous === contents;
      const bootstrap = () =>
        execFileSync("/bin/launchctl", [
          "bootstrap",
          `gui/${process.getuid()}`,
          file(label),
        ]);
      const restore = async () => {
        if (!previous) return;
        await bootout(label);
        writeFileSync(file(label), previous, { mode: 0o600 });
        bootstrap();
        if (label === labels.web) {
          for (let attempt = 0; attempt < 40; attempt++) {
            if (
              (await json("http://localhost:5173/healthz"))?.name ===
              "RPI360 Workbench"
            )
              return;
            await delay(500);
          }
          throw new Error(
            `Previous workbench was reloaded but is not healthy; inspect ${logs}`,
          );
        }
      };
      if (!unchanged) {
        await bootout(label);
        writeFileSync(file(label), contents, { mode: 0o600 });
      }
      try {
        if (!loaded(label)) bootstrap();
      } catch (error) {
        if (!unchanged) await restore();
        throw error;
      }
      return !unchanged && previous ? restore : null;
    }
    if (!loaded(labels.web)) {
      const { createServer } = await import("node:net");
      await new Promise((resolve, reject) => {
        const probe = createServer();
        probe.on("error", () =>
          reject(
            new Error(
              "Port 5173 belongs to another process. Close that server, then retry.",
            ),
          ),
        );
        probe.listen(5173, "127.0.0.1", () => probe.close(resolve));
      });
    }
    const restoreWeb = await install(labels.web, [
      node,
      join(release, "server.mjs"),
      join(release, "web"),
    ]);
    let ready = false;
    for (let attempt = 0; attempt < 40; attempt++) {
      if (
        (await json("http://localhost:5173/healthz"))?.name ===
        "RPI360 Workbench"
      ) {
        ready = true;
        break;
      }
      await delay(500);
    }
    if (!ready) {
      if (restoreWeb) await restoreWeb();
      throw new Error(
        `Workbench did not start; ${restoreWeb ? "restored the previous service; " : ""}inspect ${logs}`,
      );
    }
    const link = join(base, `current-${process.pid}`);
    symlinkSync(release, link);
    renameSync(link, join(base, "current"));
    console.log(
      "Workbench ready: http://localhost:5173 — you can close this terminal.",
    );
    if (!camera) {
      console.log(
        "Local editing is available. Add a Pi with: make preview CAMERA=user@raspberrypi.local",
      );
      return;
    }
    const keys = join(base, "ssh");
    mkdirSync(keys, { mode: 0o700, recursive: true });
    const key = join(
      keys,
      createHash("sha256").update(camera).digest("hex").slice(0, 16),
    );
    const marker = key + ".authorized";
    if (!existsSync(key))
      await run(
        "/usr/bin/ssh-keygen",
        [
          "-q",
          "-t",
          "ed25519",
          "-N",
          "",
          "-f",
          key,
          "-C",
          "rpi360-api-forwarding",
        ],
        root,
      );
    chmodSync(key, 0o600);
    if (!existsSync(marker) || action === "authorize") {
      console.log(
        "One-time SSH setup: adding a dedicated forwarding key for Pi port 8765. Enter your normal SSH password if requested; it is not stored.",
      );
      await run(
        "/usr/bin/ssh",
        ["-T", camera, installKeyCommand(readFileSync(key + ".pub", "utf8"))],
        root,
      );
      writeFileSync(marker, camera + "\n", { mode: 0o600 });
    }
    if (!loaded(labels.tunnel)) {
      const { createServer } = await import("node:net");
      await new Promise((resolve, reject) => {
        const probe = createServer();
        probe.on("error", () =>
          reject(
            new Error(
              "Port 8765 belongs to another tunnel. Close it before enabling automatic reconnect. Workbench stays running.",
            ),
          ),
        );
        probe.listen(8765, "127.0.0.1", () => probe.close(resolve));
      });
    }
    await install(labels.tunnel, tunnelArgs(camera, key));
    writeFileSync(
      configPath,
      JSON.stringify({ camera, release }, null, 2) + "\n",
      { mode: 0o600 },
    );
    let connected = false;
    for (let attempt = 0; attempt < 25; attempt++) {
      if (
        (await json("http://localhost:5173/api/v1/info"))?.access_mode ===
        "local"
      ) {
        connected = true;
        break;
      }
      await delay(500);
    }
    console.log(
      connected
        ? "Camera connected. Open Camera → Open live preview."
        : "Camera is offline/reconnecting. The workbench stays available; the SSH service retries automatically.",
    );
    console.log(
      "Starts at Mac login and restarts after crashes. Status: make preview-status · Stop: make preview-stop",
    );
  } finally {
    rmSync(lock, { force: true });
  }
}
