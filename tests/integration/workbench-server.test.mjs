import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, writeFile, mkdir, symlink, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer, request } from "node:http";
import { createWorkbenchServer } from "../../tools/workbench-server.mjs";

async function listen(server, port = 0) {
  await new Promise((resolve) => server.listen(port, "127.0.0.1", resolve));
  return server.address().port;
}
async function close(server) {
  server.closeAllConnections();
  await new Promise((resolve) => server.close(resolve));
}
async function fixture(t) {
  const dir = await mkdtemp(join(tmpdir(), "rpi360-workbench-"));
  const root = join(dir, "web");
  await mkdir(root);
  await writeFile(join(root, "index.html"), "<h1>RPI360</h1>");
  await writeFile(join(root, "source.mp4"), "0123456789");
  await writeFile(join(root, "render.wasm"), "wasm");
  const upstream = createServer((req, res) => {
    res.writeHead(req.headers.range ? 206 : 200, {
      "Content-Type": "application/json",
    });
    res.end(
      JSON.stringify({
        path: req.url,
        range: req.headers.range,
        authorization: req.headers.authorization,
        host: req.headers.host,
      }),
    );
  });
  const upstreamPort = await listen(upstream);
  const web = createWorkbenchServer({ root, upstreamPort });
  const port = await listen(web),
    url = `http://127.0.0.1:${port}`;
  t.after(async () => {
    await close(web);
    await close(upstream);
    await rm(dir, { recursive: true });
  });
  return { dir, root, upstream, upstreamPort, url };
}

test("camera outage leaves the workbench usable and proxy recovers without restart", async (t) => {
  const { url, upstream, upstreamPort } = await fixture(t);
  assert.equal((await fetch(url + "/api/v1/info")).status, 200);
  await close(upstream);
  assert.equal((await fetch(url + "/api/v1/info")).status, 502);
  assert.equal((await fetch(url + "/")).status, 200);
  assert.equal(
    (await (await fetch(url + "/healthz")).json()).name,
    "RPI360 Workbench",
  );
  await listen(upstream, upstreamPort);
  assert.equal((await fetch(url + "/v1/info")).status, 200);
});

test("health does not claim readiness when the installed build is missing", async (t) => {
  const { root, url } = await fixture(t);
  await rm(join(root, "index.html"));
  assert.equal((await fetch(url + "/healthz")).status, 503);
});

test("camera proxy preserves download ranges and supports both SDK URL forms", async (t) => {
  const { url, upstreamPort } = await fixture(t);
  for (const prefix of ["/api", ""]) {
    const r = await fetch(
      url + prefix + "/v1/recordings/id/files/camera0.mp4",
      { headers: { Range: "bytes=2-4" } },
    );
    assert.equal(r.status, 206);
    assert.deepEqual(await r.json(), {
      path: "/v1/recordings/id/files/camera0.mp4",
      range: "bytes=2-4",
      host: `127.0.0.1:${upstreamPort}`,
    });
  }
});

test("static output serves WASM, HEAD and bounded byte ranges", async (t) => {
  const { url } = await fixture(t);
  const wasm = await fetch(url + "/render.wasm");
  assert.equal(wasm.headers.get("content-type"), "application/wasm");
  const head = await fetch(url + "/source.mp4", { method: "HEAD" });
  assert.equal(head.headers.get("content-length"), "10");
  assert.equal(await head.text(), "");
  const range = await fetch(url + "/source.mp4", {
    headers: { Range: "bytes=3-5" },
  });
  assert.equal(range.status, 206);
  assert.equal(await range.text(), "345");
  assert.equal(range.headers.get("content-range"), "bytes 3-5/10");
  assert.equal(
    (await fetch(url + "/source.mp4", { headers: { Range: "bytes=100-" } }))
      .status,
    416,
  );
});

test("untrusted browser requests are rejected before reaching the camera", async (t) => {
  const { url } = await fixture(t);
  for (const headers of [
    { Origin: "https://attacker.example" },
    { Host: "attacker.example" },
    { "Sec-Fetch-Site": "cross-site" },
  ]) {
    const status = await new Promise((resolve, reject) => {
      const req = request(
        url + "/api/v1/capture/start",
        { method: "POST", headers },
        (res) => {
          res.resume();
          resolve(res.statusCode);
        },
      );
      req.on("error", reject);
      req.end();
    });
    assert.equal(status, 403, JSON.stringify(headers));
  }
  assert.equal(
    (await fetch(url + "/api/v1/info", { headers: { Origin: url } })).status,
    200,
  );
});

test("a normal link from another site can open the workbench document", async (t) => {
  const { url } = await fixture(t);
  const status = await new Promise((resolve, reject) => {
    const req = request(
      url + "/",
      {
        headers: {
          "Sec-Fetch-Site": "cross-site",
          "Sec-Fetch-Mode": "navigate",
          "Sec-Fetch-Dest": "document",
        },
      },
      (res) => {
        res.resume();
        resolve(res.statusCode);
      },
    );
    req.on("error", reject);
    req.end();
  });
  assert.equal(status, 200);
});

test("static paths cannot escape the release, including through symlinks", async (t) => {
  const { dir, root, url } = await fixture(t);
  await writeFile(join(dir, "private.txt"), "outside the web release");
  await symlink(join(dir, "private.txt"), join(root, "escape.txt"));
  assert.equal((await fetch(url + "/escape.txt")).status, 403);
  assert.equal((await fetch(url + "/%2e%2e%2fprivate.txt")).status, 403);
  assert.equal((await fetch(url + "/missing.js")).status, 404);
  assert.equal((await fetch(url + "/", { method: "POST" })).status, 405);
});
