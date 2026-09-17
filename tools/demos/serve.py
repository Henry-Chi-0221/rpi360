"""Serve the locally rendered gallery on loopback; no source footage upload."""

import argparse
import html
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Gallery(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "demos/outputs"), **kwargs)

    def do_GET(self):
        if self.path != "/":
            return super().do_GET()
        cards = "".join(
            '<article><video controls preload="metadata" src="'
            + html.escape(p.name)
            + '"></video><h2>'
            + html.escape(p.stem.replace("-", " ").title().replace("Fov", "FOV"))
            + "</h2></article>"
            for p in sorted((ROOT / "demos/outputs").glob("*.mp4"))
        )
        page = (
            '<!doctype html><meta charset="utf-8"><title>RPI360 Demo Gallery</title>'
            "<style>body{margin:4vw;background:#101610;color:#e4e8df;"
            "font:16px system-ui}"
            "h1{font-size:40px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:32px}"
            "video{width:100%;height:360px;background:#000}h2{font-size:18px}</style>"
            "<h1>One capture. New perspectives.</h1><p>RPI360 v2 · "
            "Reproducible camera paths. "
            "Titles stay outside the footage.</p><main>" + cards + "</main>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", type=int, default=5174)
    args = p.parse_args()
    print(f"Gallery: http://localhost:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Gallery).serve_forever()
