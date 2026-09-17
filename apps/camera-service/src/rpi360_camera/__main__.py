import argparse
import os
from pathlib import Path

import uvicorn

from .api import create_app
from .capture import CaptureEngine, load_calibration


def main():
    parser = argparse.ArgumentParser(description="RPI360 headless camera service")
    parser.add_argument(
        "--data-dir", type=Path, default=Path.home() / ".local/share/rpi360"
    )
    parser.add_argument("--calibration", type=Path)
    parser.add_argument(
        "--auto-capture",
        action="store_true",
        help="Start both sensors with the service; never starts recording",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--origin", action="append", default=[])
    parser.add_argument("--cert")
    parser.add_argument("--key")
    parser.add_argument("--web-root", type=Path, help="built Web workbench directory")
    parser.add_argument(
        "--api-token-file",
        type=Path,
        help="optional bearer token file; required for direct LAN listening",
    )
    args = parser.parse_args()
    token = None
    if args.api_token_file:
        try:
            if args.api_token_file.stat().st_mode & 0o077:
                parser.error("API token file must be private (chmod 600)")
            token = args.api_token_file.read_text().strip()
            if len(token) < 32 or not token.isascii():
                parser.error("API token must contain at least 32 ASCII characters")
        except OSError as exc:
            parser.error(f"cannot read API token file: {exc}")
    if args.host not in ("127.0.0.1", "::1", "localhost") and not (
        args.cert and args.key and token
    ):
        parser.error(
            "network listening requires --cert, --key and --api-token-file; "
            "the default SSH workflow needs none of these"
        )
    os.umask(0o077)
    engine = CaptureEngine(args.data_dir, load_calibration(args.calibration))
    origins = args.origin or ["http://localhost:5173", "http://127.0.0.1:5173"]
    app = create_app(
        engine, origins, args.web_root, api_token=token, auto_capture=args.auto_capture
    )
    print("Access: " + app.state.access.mode + "; no pairing code is used.", flush=True)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        ssl_certfile=args.cert,
        ssl_keyfile=args.key,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
