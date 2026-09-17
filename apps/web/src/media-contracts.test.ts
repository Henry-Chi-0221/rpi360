import { describe, it, expect } from "vitest";
import { readBundleZip } from "../../../packages/web-sdk/src/media/zip";
import { spawnSync } from "node:child_process";
import { readManifest } from "../../../packages/web-sdk/src/media/manifest";

// Python's standard ZIP writer provides an independent encoder, including ZIP64.
function zip(names = ["bundle.r360/manifest.json"], zip64 = false): Blob {
  const script = `import io,sys,zipfile\nzipfile.ZIP64_LIMIT=${zip64 ? "1" : "2147483647"}\nb=io.BytesIO()\nwith zipfile.ZipFile(b,'w',compression=zipfile.ZIP_STORED) as z:\n for n in sys.argv[1:]:z.writestr(n,'{\"test\":true}')\nsys.stdout.buffer.write(b.getvalue())`;
  const result = spawnSync("python3", ["-c", script, ...names]);
  if (result.status) throw new Error(result.stderr.toString());
  return new Blob([new Uint8Array(result.stdout)]);
}
describe("bounded bundle ZIP reader", () => {
  it.each([false, true])(
    "reads independent ZIP64=%s archives without inflating video",
    async (zip64) => {
      const entries = await readBundleZip(zip(undefined, zip64));
      expect(JSON.parse(await entries.get("manifest.json")!.text())).toEqual({
        test: true,
      });
    },
  );
  it("rejects collisions after stripping the bundle folder", async () => {
    await expect(
      readBundleZip(zip(["a/manifest.json", "b/manifest.json"])),
    ).rejects.toThrow("Ambiguous");
  });
  it("rejects traversal and truncated files", async () => {
    await expect(readBundleZip(zip(["../manifest.json"]))).rejects.toThrow(
      "unsafe",
    );
    const good = zip();
    await expect(
      readBundleZip(good.slice(0, good.size - 10)),
    ).rejects.toThrow();
  });
});

describe("recording import contract", () => {
  const manifest = () => ({
    schema_version: 2,
    id: "a".repeat(32),
    state: "complete",
    clock: { unit: "microseconds" },
    calibration: "calibration.json",
    streams: [0, 1].map((camera) => ({
      camera,
      path: `camera${camera}.mp4`,
      width: 1640,
      height: 1232,
      codec: "h264",
      media_start_offset_us: 123456,
    })),
    files: ["camera0.mp4", "camera1.mp4", "calibration.json"].map((path) => ({
      path,
      bytes: 100,
      sha256: "b".repeat(64),
    })),
  });
  const blob = (value: unknown) => new Blob([JSON.stringify(value)]);
  it("retains nonzero source clock offsets and unknown synchronization", async () => {
    const parsed = await readManifest(blob(manifest()));
    expect(parsed.streams[1].media_start_offset_us).toBe(123456);
    expect(parsed.sync).toBeUndefined();
  });
  it("rejects duplicated cameras and unhashed sources", async () => {
    const duplicate = manifest();
    duplicate.streams[1] = duplicate.streams[0];
    await expect(readManifest(blob(duplicate))).rejects.toThrow("camera track");
    const unhashed = manifest();
    unhashed.files.shift();
    await expect(readManifest(blob(unhashed))).rejects.toThrow("checksum");
  });
  it("rejects unsafe offsets and oversized metadata before decoding", async () => {
    const unsafe = manifest();
    unsafe.streams[0].media_start_offset_us = 2 ** 54;
    await expect(readManifest(blob(unsafe))).rejects.toThrow("camera track");
    await expect(
      readManifest(new Blob([new Uint8Array(1024 * 1024 + 1)])),
    ).rejects.toThrow("1 MiB");
  });
});
