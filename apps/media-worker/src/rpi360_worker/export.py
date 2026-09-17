"""Bounded-memory VFR decode -> shared Rust GPU renderer -> H.264 export."""

import argparse
import hashlib
import json
import os
import struct
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

import av
import numpy as np


class Track:
    def __init__(self, path, index=0, offset_us=0):
        self.container = av.open(str(path))
        self.stream = self.container.streams.video[index]
        self.frames = iter(self.container.decode(self.stream))
        self.current = None
        self.next = next(self.frames, None)
        self.offset_us = offset_us
        self.last_request = None

    def at(self, time_us):
        if self.last_request is not None and time_us < self.last_request:
            self.container.seek(
                max(0, int((time_us - self.offset_us) / 1e6 / self.stream.time_base)),
                stream=self.stream,
                backward=True,
            )
            self.frames = iter(self.container.decode(self.stream))
            self.current = None
            self.next = next(self.frames, None)
        self.last_request = time_us

        def timestamp(f):
            return round(f.pts * f.time_base * 1_000_000) + self.offset_us

        while self.next is not None and (
            self.current is None or timestamp(self.next) <= time_us
        ):
            self.current = self.next
            self.next = next(self.frames, None)
        if self.current is None:
            raise ValueError("empty source track")
        return self.current, timestamp(self.current)

    def close(self):
        self.container.close()


def export(
    recipe,
    source_root,
    output,
    renderer=None,
    on_progress=lambda p: None,
    cancelled=lambda: False,
):
    from rpi360.core import evaluate_project

    root = Path(source_root).resolve()
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    render = Path(
        renderer or os.environ.get("RPI360_RENDER_BIN", "target/release/rpi360-render")
    ).resolve()
    project = recipe["project"]
    spec = recipe["output"]
    width, height = spec["width"], spec["height"]
    fps = spec.get("fps", 30)
    paths = [(root / s["path"]).resolve() for s in recipe["sources"]]
    for path in paths:
        if root not in path.parents:
            raise ValueError("source path escapes source root")
    tracks = [
        Track(p, s.get("track", 0), s.get("media_start_offset_us", 0))
        for p, s in zip(paths, recipe["sources"], strict=False)
    ]
    process = None
    container = None
    errors = []
    part = output.with_name(output.name + ".partial")
    if part.exists():
        raise FileExistsError(part)
    try:
        initial = [
            t.at(
                recipe.get(
                    "freeze_source_us", evaluate_project(project, 0)["source_time_us"]
                )
            )[0]
            for t in tracks
        ]
        sw, sh = initial[0].width, initial[0].height
        if any((f.width, f.height) != (sw, sh) for f in initial):
            raise ValueError("source dimensions must match")
        with tempfile.TemporaryDirectory(prefix="rpi360-export-") as temp:
            temp = Path(temp)
            cal = temp / "calibration.json"
            cal.write_text(json.dumps(recipe["calibration"]))
            proj = temp / "project.json"
            proj.write_text(json.dumps(project))
            log = (temp / "renderer.log").open("w+")
            process = subprocess.Popen(
                [
                    str(render),
                    "--pipe",
                    str(cal),
                    str(proj),
                    str(sw * 2),
                    str(sh),
                    str(width),
                    str(height),
                    "true",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log,
            )
            container = av.open(
                str(part), "w", format="mp4", options={"movflags": "+faststart"}
            )
            stream = container.add_stream("libx264", rate=Fraction(fps))
            stream.width = width
            stream.height = height
            stream.pix_fmt = "yuv420p"
            stream.options = {"crf": "19", "preset": "fast"}
            count = (project["duration_us"] * fps + 999999) // 1000000
            output_bytes = width * height * 4
            for n in range(count):
                if cancelled():
                    raise InterruptedError("export cancelled; source files unchanged")
                time_us = round(n / fps * 1_000_000)
                state = evaluate_project(project, time_us)
                target = recipe.get("freeze_source_us", state["source_time_us"])
                frames = []
                pts = []
                for i, track in enumerate(tracks):
                    correction = (project.get("alignment_us") or 0) if i == 1 else 0
                    frame, stamp = track.at(target + correction)
                    frames.append(frame.to_ndarray(format="rgba"))
                    pts.append(stamp - correction)
                errors.append(abs(pts[0] - pts[1]))
                packed = np.concatenate(frames, axis=1)
                process.stdin.write(struct.pack("<q", time_us))
                process.stdin.write(packed.tobytes())
                process.stdin.flush()
                pixels = process.stdout.read(output_bytes)
                if len(pixels) != output_bytes:
                    log.seek(0)
                    raise RuntimeError("GPU renderer stopped: " + log.read())
                frame = av.VideoFrame.from_ndarray(
                    np.frombuffer(pixels, np.uint8).reshape(height, width, 4),
                    format="rgba",
                )
                frame.pts = n
                for packet in stream.encode(frame):
                    container.mux(packet)
                on_progress((n + 1) / count)
            for packet in stream.encode():
                container.mux(packet)
            container.close()
            container = None
            process.stdin.close()
            process.wait(timeout=30)
            if process.returncode:
                log.seek(0)
                raise RuntimeError(log.read())
            log.close()
        with av.open(str(part)) as verify:
            actual = sum(1 for _ in verify.decode(video=0))
            if actual != count:
                raise RuntimeError(f"export verification: {actual} of {count} frames")
        os.replace(part, output)
        report = {
            "output": output.name,
            "frames": count,
            "fps": fps,
            "sha256": hashlib.file_digest(output.open("rb"), "sha256").hexdigest(),
            "max_selected_pair_delta_us": max(errors),
            "source_alignment_known": project.get("alignment_us") is not None,
            "kind": "360 still-frame reframing"
            if "freeze_source_us" in recipe
            else "VFR source with virtual camera motion",
        }
        output.with_suffix(".report.json").write_text(json.dumps(report, indent=2))
        return report
    finally:
        if container:
            container.close()
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        for track in tracks:
            track.close()
        # Keep a failed partial for diagnosis; never delete source recordings.


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("recipe", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--renderer")
    args = p.parse_args()
    print(
        json.dumps(
            export(
                json.loads(args.recipe.read_text()),
                args.source_root,
                args.output,
                args.renderer,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
