#!/usr/bin/env node
// Local built workbench: its lifetime never depends on the camera connection.
import { createServer, request } from "node:http";
import { createReadStream, existsSync } from "node:fs";
import { realpath, stat } from "node:fs/promises";
import { resolve, extname, sep } from "node:path";
import { pathToFileURL } from "node:url";

const mime = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".wasm": "application/wasm",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
  ".mp4": "video/mp4",
};
const loopbackHost = (value) =>
  ["localhost", "127.0.0.1", "[::1]"].includes(value);
function reply(res, code, value) {
  res.writeHead(code, {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
  });
  res.end(JSON.stringify(value));
}

export function createWorkbenchServer({ root, upstreamPort = 8765 }) {
  return createServer(async (req, res) => {
    try {
      const target = new URL(req.url, `http://${req.headers.host}`);
      const origin = req.headers.origin;
      const documentNavigation =
        req.method === "GET" &&
        req.headers["sec-fetch-mode"] === "navigate" &&
        req.headers["sec-fetch-dest"] === "document" &&
        ["/", "/index.html", "/api-example.html"].includes(target.pathname);
      if (
        !loopbackHost(target.hostname) ||
        (origin && origin !== target.origin) ||
        (!origin &&
          req.headers["sec-fetch-site"] === "cross-site" &&
          !documentNavigation)
      ) {
        reply(res, 403, { detail: "Use the local workbench origin." });
        return;
      }
      if (target.pathname === "/healthz") {
        if (!existsSync(resolve(root, "index.html"))) {
          reply(res, 503, { detail: "Workbench build is missing" });
          return;
        }
        reply(res, 200, { name: "RPI360 Workbench", version: 1 });
        return;
      }
      if (
        target.pathname.startsWith("/api/v1/") ||
        target.pathname.startsWith("/v1/")
      ) {
        const headers = { ...req.headers, host: `127.0.0.1:${upstreamPort}` };
        for (const name of [
          "connection",
          "upgrade",
          "proxy-authorization",
          "forwarded",
          "x-forwarded-for",
        ])
          delete headers[name];
        const remote = request(
          {
            host: "127.0.0.1",
            port: upstreamPort,
            path:
              target.pathname.replace(/^\/api(?=\/v1\/)/, "") + target.search,
            method: req.method,
            headers,
          },
          (response) => {
            res.writeHead(response.statusCode, response.headers);
            response.on("error", () => res.destroy());
            response.pipe(res);
          },
        );
        // SSE/media responses remain streaming; no whole-file buffering.
        remote.setTimeout(15000, () =>
          remote.destroy(new Error("camera timed out")),
        );
        remote.on("error", () => {
          if (!res.headersSent)
            reply(res, 502, {
              detail:
                "Camera is reconnecting. The workbench remains available for local editing.",
            });
          else res.destroy();
        });
        res.on("close", () => remote.destroy());
        req.pipe(remote);
        return;
      }
      if (!["GET", "HEAD"].includes(req.method)) {
        reply(res, 405, { detail: "Method not allowed" });
        return;
      }
      let name;
      try {
        name = decodeURIComponent(target.pathname);
      } catch {
        reply(res, 400, { detail: "Invalid path" });
        return;
      }
      const directory = await realpath(root);
      const path = resolve(
        directory,
        "." + (name === "/" ? "/index.html" : name),
      );
      let actual;
      try {
        actual = await realpath(path);
      } catch {
        reply(res, 404, { detail: "File not found" });
        return;
      }
      if (!actual.startsWith(directory + sep) || name.includes("\0")) {
        reply(res, 403, { detail: "Invalid path" });
        return;
      }
      const file = await stat(actual);
      if (!file.isFile()) {
        reply(res, 404, { detail: "File not found" });
        return;
      }
      let start = 0,
        end = file.size - 1,
        code = 200;
      const responseHeaders = {
        "Content-Type": mime[extname(actual)] ?? "application/octet-stream",
        "Cache-Control": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "Accept-Ranges": "bytes",
      };
      if (req.headers.range) {
        const range = /^bytes=(\d+)-(\d*)$/.exec(req.headers.range);
        if (
          !range ||
          Number(range[1]) >= file.size ||
          (range[2] && Number(range[2]) < Number(range[1]))
        ) {
          res.writeHead(416, { "Content-Range": `bytes */${file.size}` });
          res.end();
          return;
        }
        start = Number(range[1]);
        end = range[2] ? Math.min(Number(range[2]), end) : end;
        code = 206;
        responseHeaders["Content-Range"] = `bytes ${start}-${end}/${file.size}`;
      }
      responseHeaders["Content-Length"] = Math.max(0, end - start + 1);
      res.writeHead(code, responseHeaders);
      if (req.method === "HEAD" || file.size === 0) {
        res.end();
        return;
      }
      const stream = createReadStream(actual, { start, end });
      stream.on("error", () => res.destroy());
      res.on("close", () => stream.destroy());
      stream.pipe(res);
    } catch {
      if (!res.headersSent)
        reply(res, 500, { detail: "Workbench request failed" });
      else res.destroy();
    }
  });
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href
) {
  const server = createWorkbenchServer({ root: process.argv[2] });
  server.listen(5173, "127.0.0.1", () =>
    console.log("RPI360 Workbench ready at http://localhost:5173"),
  );
  server.on("error", (error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
  for (const signal of ["SIGINT", "SIGTERM"])
    process.on(signal, () => {
      server.close();
      server.closeAllConnections();
    });
}
