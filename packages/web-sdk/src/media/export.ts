import {
  Output,
  Mp4OutputFormat,
  CanvasSource,
  StreamTarget,
  canEncodeVideo,
} from "mediabunny";
import { Renderer, evaluate } from "../renderer";
import type { PairSource } from "./source";
import type { EditProject } from "../types";
import { quota } from "./storage";
import { sphericalVideo } from "./spherical";
export async function exportVideo(
  source: PairSource,
  project: EditProject,
  width: number,
  height: number,
  onProgress: (n: number) => void,
  signal: AbortSignal,
  spherical = false,
) {
  if (spherical && width !== height * 2)
    throw new Error("360 export requires a 2:1 canvas");
  const fps = 30;
  const bitrate = 8_000_000;
  if (!(await canEncodeVideo("avc", { width, height, bitrate })))
    throw new Error("H.264 export is unavailable on this device");
  await quota(
    (((project.duration_us / 1e6) * bitrate) / 8) * (spherical ? 2.5 : 1.25),
  );
  const root = await navigator.storage.getDirectory();
  const dir = await root.getDirectoryHandle("rpi360-exports", { create: true });
  const name = crypto.randomUUID() + ".mp4";
  const handle = await dir.getFileHandle(name, { create: true });
  const writer = await handle.createWritable();
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  let renderer: Renderer | undefined;
  let output: Output | undefined;
  try {
    renderer = await Renderer.create(canvas, source.calibration);
    output = new Output({
      format: new Mp4OutputFormat({ fastStart: "fragmented" }),
      target: new StreamTarget(writer),
    });
    const track = new CanvasSource(canvas, { codec: "avc", bitrate });
    output.addVideoTrack(track, { frameRate: fps });
    await output.start();
    const count = Math.ceil((project.duration_us / 1e6) * fps);
    for (let n = 0; n < count; n++) {
      signal.throwIfAborted();
      const t = n / fps;
      const evaluated = evaluate(project, t * 1e6);
      const pair = await source.frame(
        evaluated.source_time_us / 1e6,
        project.alignment_us,
        true,
      );
      renderer.upload(pair.canvas, pair.width, pair.height);
      renderer.draw(
        spherical
          ? {
              ...evaluated.view,
              projection: "equirectangular",
              orientation: [0, 0, 0, 1],
              spin_deg: 0,
            }
          : evaluated.view,
        width,
        height,
        true,
      );
      await track.add(t, 1 / fps, { keyFrame: n % 30 === 0 });
      onProgress((n + 1) / count);
    }
    track.close();
    await output.finalize();
    if (spherical) {
      const taggedName = name.replace(".mp4", "-360.mp4");
      const tagged = await dir.getFileHandle(taggedName, { create: true });
      try {
        const file = await sphericalVideo(
          await handle.getFile(),
          tagged,
          signal,
        );
        await dir.removeEntry(name);
        return { file, cleanup: () => dir.removeEntry(taggedName) };
      } catch (e) {
        await dir.removeEntry(taggedName).catch(() => {});
        throw e;
      }
    }
    return {
      file: await handle.getFile(),
      cleanup: () => dir.removeEntry(name),
    };
  } catch (e) {
    await output?.cancel().catch(() => {});
    await writer.abort().catch(() => {});
    await dir.removeEntry(name).catch(() => {});
    throw e;
  } finally {
    renderer?.dispose();
  }
}
