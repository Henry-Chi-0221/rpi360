import {
  Input,
  MP4,
  BlobSource,
  CanvasSink,
  type InputVideoTrack,
} from "mediabunny";
import { createSHA256 } from "hash-wasm";
import { readBundleZip } from "./zip";
import { readManifest } from "./manifest";
export interface PairSource {
  id: string;
  duration: number;
  calibration: unknown;
  alignmentKnown: boolean;
  frame(
    time: number,
    alignmentUs?: number | null,
    fullResolution?: boolean,
  ): Promise<{
    canvas: HTMLCanvasElement;
    width: number;
    height: number;
    deltaUs: number;
  }>;
  dispose(): void;
}
export async function sha256(blob: Blob, signal?: AbortSignal) {
  const hash = await createSHA256();
  for (let i = 0; i < blob.size; i += 1024 * 1024) {
    signal?.throwIfAborted();
    hash.update(
      new Uint8Array(await blob.slice(i, i + 1024 * 1024).arrayBuffer()),
    );
  }
  return hash.digest();
}
export class RecordedSource implements PairSource {
  private canvas = document.createElement("canvas");
  private ctx = this.canvas.getContext("2d")!;
  private sinks: CanvasSink[] = [];
  private fullSinks: CanvasSink[] | null = null;
  private constructor(
    public id: string,
    public duration: number,
    public calibration: unknown,
    public alignmentKnown: boolean,
    private inputs: Input[],
    private offsets: number[],
    private tracks: InputVideoTrack[],
    private width: number,
    private height: number,
  ) {
    this.canvas.width = width * 2;
    this.canvas.height = height;
    this.sinks = tracks.map(
      (track) =>
        new CanvasSink(track, { width, height, poolSize: 2, fit: "fill" }),
    );
  }
  static async open(
    files: File[] | Map<string, Blob>,
    signal?: AbortSignal,
  ): Promise<RecordedSource> {
    let entries: Map<string, Blob>;
    if (files instanceof Map) entries = files;
    else if (files.length === 1 && files[0].name.endsWith(".zip"))
      entries = await readBundleZip(files[0]);
    else entries = new Map(files.map((f) => [f.name, f]));
    const manifest = entries.get("manifest.json");
    const inputs: Input[] = [];
    try {
      let calibration: unknown;
      let tracks: InputVideoTrack[] = [];
      let offsets = [0, 0];
      let id: string;
      let known = false;
      if (manifest) {
        const m = await readManifest(manifest);
        id = m.id;
        if (!m.calibration)
          throw new Error(
            "This recording has no calibration. Recordings remain usable after calibration is supplied.",
          );
        const cal = entries.get(m.calibration);
        if (!cal) throw new Error("Calibration snapshot missing");
        if (cal.size > 1024 * 1024) throw new Error("Calibration exceeds 1 MiB");
        for (const item of m.files) {
          signal?.throwIfAborted();
          const file = entries.get(item.path);
          if (
            !file ||
            file.size !== item.bytes ||
            (await sha256(file, signal)) !== item.sha256
          )
            throw new Error(`Checksum mismatch: ${item.path}`);
        }
        calibration = JSON.parse(await cal.text());
        for (const stream of [...m.streams].sort(
          (a, b) => a.camera - b.camera,
        )) {
          const blob = entries.get(stream.path);
          if (!blob) throw new Error("Source track missing");
          const input = new Input({
            source: new BlobSource(blob),
            formats: [MP4],
          });
          inputs.push(input);
          const t = await input.getPrimaryVideoTrack();
          if (!t) throw new Error("No video track");
          tracks.push(t);
        }
        offsets = m.streams
          .sort((a, b) => a.camera - b.camera)
          .map((s) => s.media_start_offset_us / 1e6);
        known = m.sync?.method === "libcamera-software";
        if (!offsets.every(Number.isFinite))
          throw new Error("Missing media-to-session time mapping");
      } else {
        if (entries.size !== 1)
          throw new Error(
            "Select a .r360 folder, .r360.zip, or legacy two-track .r360.mp4",
          );
        const [name, blob] = [...entries][0];
        id = name;
        const input = new Input({
          source: new BlobSource(blob),
          formats: [MP4],
        });
        inputs.push(input);
        tracks = await input.getVideoTracks();
        if (tracks.length !== 2)
          throw new Error("Expected two fisheye video tracks");
        const tags = await input.getMetadataTags();
        const raw = tags.raw?.rpi360;
        if (typeof raw !== "string")
          throw new Error("Legacy RPI360 calibration metadata is missing");
        const meta = JSON.parse(raw);
        calibration = meta.calibration;
        const stream0 = meta.streams?.camera_0,
          stream1 = meta.streams?.camera_1;
        if (stream0 && stream1) {
          const ordered = [stream0, stream1].map((s) =>
            tracks.find((t) => t.id === s.track_id),
          );
          if (ordered.every(Boolean)) tracks = ordered as InputVideoTrack[];
          for (const [i, s] of [stream0, stream1].entries()) {
            const c = (calibration as any)[`camera_${i}`];
            c.width ??= s.width;
            c.height ??= s.height;
          }
        }
      }
      if (!(await Promise.all(tracks.map((t) => t.canDecode()))).every(Boolean))
        throw new Error(
          "This browser cannot decode the source H.264 profile. Use a compatible browser or the optional media worker.",
        );
      const duration = Math.min(
        ...(await Promise.all(
          tracks.map(async (t, i) => (await t.computeDuration()) + offsets[i]),
        )),
      );
      const width = Math.min(1640, await tracks[0].getDisplayWidth());
      const height = Math.round(
        (width * (await tracks[0].getDisplayHeight())) /
          (await tracks[0].getDisplayWidth()),
      );
      return new RecordedSource(
        id,
        duration,
        calibration,
        known,
        inputs,
        offsets,
        tracks,
        width,
        height,
      );
    } catch (e) {
      inputs.forEach((i) => i.dispose());
      throw e;
    }
  }
  async frame(
    time: number,
    alignmentUs: number | null = 0,
    fullResolution = false,
  ) {
    let width = this.width,
      height = this.height,
      sinks = this.sinks;
    if (fullResolution) {
      width = await this.tracks[0].getDisplayWidth();
      height = await this.tracks[0].getDisplayHeight();
      this.fullSinks ??= this.tracks.map(
        (t) => new CanvasSink(t, { width, height, poolSize: 1, fit: "fill" }),
      );
      sinks = this.fullSinks;
    }
    if (this.canvas.width !== width * 2 || this.canvas.height !== height) {
      this.canvas.width = width * 2;
      this.canvas.height = height;
    }
    const result = await Promise.all(
      sinks.map((s, i) =>
        s.getCanvas(
          Math.max(
            0,
            time - this.offsets[i] + (i === 1 ? (alignmentUs ?? 0) / 1e6 : 0),
          ),
        ),
      ),
    );
    if (result.some((r) => !r))
      throw new Error("No complete frame pair at this time");
    result.forEach((r, i) =>
      this.ctx.drawImage(r!.canvas, i * width, 0, width, height),
    );
    return {
      canvas: this.canvas,
      width: width * 2,
      height,
      deltaUs: Math.round(
        (result[1]!.timestamp +
          this.offsets[1] -
          (alignmentUs ?? 0) / 1e6 -
          (result[0]!.timestamp + this.offsets[0])) *
          1e6,
      ),
    };
  }
  dispose() {
    this.inputs.forEach((i) => i.dispose());
    this.canvas.width = this.canvas.height = 0;
  }
}
export class StillSource implements PairSource {
  alignmentKnown = false;
  duration = 8;
  constructor(
    public id: string,
    public calibration: unknown,
    private canvas: HTMLCanvasElement,
  ) {}
  async frame() {
    return {
      canvas: this.canvas,
      width: this.canvas.width,
      height: this.canvas.height,
      deltaUs: 0,
    };
  }
  dispose() {}
}
