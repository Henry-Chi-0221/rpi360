/** Add the standard spherical-video UUID to the video track of our fragmented MP4.
 * Media fragments use moof-relative addressing, so growing the init segment is safe.
 * The source file stays on disk; only the small moov box is buffered.
 */
const text = new TextEncoder();
function box(kind: string, payload: Uint8Array) {
  const a = new Uint8Array(payload.length + 8);
  new DataView(a.buffer).setUint32(0, a.length);
  a.set(text.encode(kind), 4);
  a.set(payload, 8);
  return a;
}
function concat(parts: Uint8Array[]) {
  const a = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let n = 0;
  for (const p of parts) {
    a.set(p, n);
    n += p.length;
  }
  return a;
}
function children(data: Uint8Array) {
  const found: { kind: string; data: Uint8Array }[] = [];
  for (let p = 0; p < data.length; ) {
    const size = new DataView(data.buffer, data.byteOffset + p).getUint32(0);
    if (size < 8 || p + size > data.length)
      throw new Error("Unsupported MP4 box");
    found.push({
      kind: new TextDecoder().decode(data.subarray(p + 4, p + 8)),
      data: data.slice(p, p + size),
    });
    p += size;
  }
  return found;
}
export async function sphericalVideo(
  file: File,
  handle: FileSystemFileHandle,
  signal: AbortSignal,
) {
  const xml = text.encode(
    '<rdf:SphericalVideo xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:GSpherical="http://ns.google.com/videos/1.0/spherical/"><GSpherical:Spherical>true</GSpherical:Spherical><GSpherical:Stitched>true</GSpherical:Stitched><GSpherical:StitchingSoftware>RPI360 v2</GSpherical:StitchingSoftware><GSpherical:ProjectionType>equirectangular</GSpherical:ProjectionType><GSpherical:StereoMode>mono</GSpherical:StereoMode></rdf:SphericalVideo>',
  );
  const uuid = Uint8Array.from(
    "ffcc8263f8554a938814587a02521fdd"
      .match(/../g)!
      .map((x) => parseInt(x, 16)),
  );
  const tag = box("uuid", concat([uuid, xml]));
  const writer = await handle.createWritable();
  let p = 0,
    added = false,
    sawMedia = false;
  try {
    while (p < file.size) {
      signal.throwIfAborted();
      const header = new DataView(await file.slice(p, p + 16).arrayBuffer());
      let size = header.getUint32(0),
        head = 8;
      if (size === 1) {
        size = Number(header.getBigUint64(8));
        head = 16;
      }
      if (size === 0) size = file.size - p;
      if (size < head || p + size > file.size)
        throw new Error("Invalid MP4 box size");
      const kind = new TextDecoder().decode(
        new Uint8Array(header.buffer, 4, 4),
      );
      if (kind === "moov") {
        if (sawMedia || size > 8 * 1024 * 1024)
          throw new Error("Expected fragmented MP4 init segment");
        const data = new Uint8Array(
          await file.slice(p + head, p + size).arrayBuffer(),
        );
        const items = children(data);
        let tagged = false;
        const mapped = items.map((item) => {
          if (item.kind !== "trak" || tagged) return item.data;
          tagged = true;
          return box("trak", concat([item.data.subarray(8), tag]));
        });
        if (!tagged) throw new Error("No video track");
        await writer.write(box("moov", concat(mapped)));
        added = true;
      } else {
        if (kind === "mdat") sawMedia = true;
        if (kind === "moof") {
          if (size > 2 * 1024 * 1024) throw new Error("Oversized fragment");
          const data = new Uint8Array(
            await file.slice(p + head, p + size).arrayBuffer(),
          );
          for (const traf of children(data).filter((x) => x.kind === "traf"))
            for (const tfhd of children(traf.data.subarray(8)).filter(
              (x) => x.kind === "tfhd",
            )) {
              const flags =
                new DataView(tfhd.data.buffer, tfhd.data.byteOffset).getUint32(
                  8,
                ) & 0xffffff;
              if (flags & 1 || !(flags & 0x020000))
                throw new Error(
                  "Fragment must use default-base-is-moof addressing",
                );
            }
        }
        for (let at = p; at < p + size; at += 1024 * 1024) {
          signal.throwIfAborted();
          await writer.write(
            await file
              .slice(at, Math.min(p + size, at + 1024 * 1024))
              .arrayBuffer(),
          );
        }
      }
      p += size;
    }
    if (!added) throw new Error("MP4 initialization missing");
    await writer.close();
    return handle.getFile();
  } catch (e) {
    await writer.abort();
    throw e;
  }
}
