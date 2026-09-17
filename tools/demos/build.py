"""Render checked-in recipes through the same native export engine as user edits."""

import argparse
import json
from pathlib import Path

from rpi360_worker.export import export

p = argparse.ArgumentParser()
p.add_argument("--source-root", type=Path, required=True)
p.add_argument("--output", type=Path, default=Path("demos/outputs"))
p.add_argument("--recipe", action="append")
args = p.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
recipes = (
    [Path(x) for x in args.recipe]
    if args.recipe
    else sorted(Path("demos/recipes").glob("*.json"))
)
for path in recipes:
    output = args.output / (path.stem + ".mp4")
    if output.exists():
        print("Already rendered:", output, flush=True)
        continue
    print("Rendering", path.stem, flush=True)
    print(
        json.dumps(export(json.loads(path.read_text()), args.source_root, output)),
        flush=True,
    )
