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
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--origin", action="append", default=[])
    parser.add_argument("--cert")
    parser.add_argument("--key")
    parser.add_argument("--web-root", type=Path, help="built Web workbench directory")
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "::1", "localhost") and not (
        args.cert and args.key
    ):
        parser.error(
            "network listening requires --cert and --key; "
            "use an SSH tunnel for loopback development"
        )
    os.umask(0o077)
    engine = CaptureEngine(args.data_dir, load_calibration(args.calibration))
    app = create_app(engine, args.origin, args.web_root)
    if not app.state.auth.clients:
        print(
            f"Local pairing code (valid 5 minutes): {app.state.auth.code}", flush=True
        )
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        ssl_certfile=args.cert,
        ssl_keyfile=args.key,
    )


if __name__ == "__main__":
    main()
