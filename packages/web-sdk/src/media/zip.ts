/** Read ZIP_STORED bundles lazily; video bytes remain backed by the source file. */
export async function readBundleZip(file: Blob): Promise<Map<string, Blob>> {
  const start = Math.max(0, file.size - 65557);
  const tail = new DataView(await file.slice(start).arrayBuffer());
  let end = -1;
  for (let i = tail.byteLength - 22; i >= 0; i--)
    if (
      tail.getUint32(i, true) === 0x06054b50 &&
      i + 22 + tail.getUint16(i + 20, true) === tail.byteLength
    ) {
      end = i;
      break;
    }
  if (end < 0) throw new Error("ZIP directory not found");
  let count = tail.getUint16(end + 10, true);
  let size = tail.getUint32(end + 12, true);
  let offset = tail.getUint32(end + 16, true);
  const safe64 = (view: DataView, pos: number) => {
    const value = Number(view.getBigUint64(pos, true));
    if (!Number.isSafeInteger(value))
      throw new Error("ZIP offset exceeds safe integer range");
    return value;
  };
  if (tail.getUint16(end + 4, true) || tail.getUint16(end + 6, true))
    throw new Error("Split ZIP archives are unsupported");
  if (count === 65535 || offset === 0xffffffff || size === 0xffffffff) {
    const locator = new DataView(
      await file.slice(start + end - 20, start + end).arrayBuffer(),
    );
    if (
      locator.byteLength !== 20 ||
      locator.getUint32(0, true) !== 0x07064b50 ||
      locator.getUint32(4, true) !== 0 ||
      locator.getUint32(16, true) !== 1
    )
      throw new Error("Invalid ZIP64 locator");
    const position = safe64(locator, 8);
    const record = new DataView(
      await file.slice(position, position + 56).arrayBuffer(),
    );
    if (
      record.byteLength !== 56 ||
      record.getUint32(0, true) !== 0x06064b50 ||
      record.getUint32(16, true) !== 0 ||
      record.getUint32(20, true) !== 0
    )
      throw new Error("Invalid ZIP64 directory");
    count = safe64(record, 32);
    size = safe64(record, 40);
    offset = safe64(record, 48);
  }
  if (size > 4 * 1024 * 1024 || count > 4096 || offset + size > file.size)
    throw new Error("Oversized or truncated ZIP directory");
  const directory = new DataView(
    await file.slice(offset, offset + size).arrayBuffer(),
  );
  let p = 0;
  const entries = new Map<string, Blob>();
  for (let n = 0; n < count; n++) {
    if (
      p + 46 > directory.byteLength ||
      directory.getUint32(p, true) !== 0x02014b50
    )
      throw new Error("Invalid ZIP directory");
    const flags = directory.getUint16(p + 8, true),
      method = directory.getUint16(p + 10, true),
      storedBytes = directory.getUint32(p + 20, true),
      plainBytes = directory.getUint32(p + 24, true),
      nameLength = directory.getUint16(p + 28, true),
      extra = directory.getUint16(p + 30, true),
      comment = directory.getUint16(p + 32, true),
      localOffset = directory.getUint32(p + 42, true);
    if (p + 46 + nameLength + extra + comment > directory.byteLength)
      throw new Error("Truncated ZIP directory entry");
    let bytes = storedBytes,
      uncompressed = plainBytes,
      local = localOffset;
    if ([bytes, uncompressed, local].includes(0xffffffff)) {
      const endExtra = p + 46 + nameLength + extra;
      let found = false;
      for (let x = p + 46 + nameLength; x + 4 <= endExtra; ) {
        const id = directory.getUint16(x, true),
          length = directory.getUint16(x + 2, true);
        const stop = x + 4 + length;
        if (stop > endExtra) throw new Error("Truncated ZIP extra field");
        if (id === 1) {
          let v = x + 4;
          const next = () => {
            if (v + 8 > stop) throw new Error("Truncated ZIP64 field");
            const n = safe64(directory, v);
            v += 8;
            return n;
          };
          if (uncompressed === 0xffffffff) uncompressed = next();
          if (bytes === 0xffffffff) bytes = next();
          if (local === 0xffffffff) local = next();
          found = true;
          break;
        }
        x = stop;
      }
      if (!found) throw new Error("Missing ZIP64 entry sizes");
    }
    const full = new TextDecoder().decode(
      new Uint8Array(directory.buffer, p + 46, nameLength),
    );
    p += 46 + nameLength + extra + comment;
    if (full.endsWith("/")) continue;
    const name = full.split("/").pop()!;
    if (flags & 1 || method !== 0 || bytes !== uncompressed)
      throw new Error(
        "Use an uncompressed .r360.zip (ZIP_STORED), or import its folder",
      );
    if (
      full.startsWith("/") ||
      full.includes("\\") ||
      full.includes("\0") ||
      full.split("/").some((x) => x === "..") ||
      entries.has(name)
    )
      throw new Error("Ambiguous or unsafe ZIP filename");
    const header = new DataView(
      await file.slice(local, local + 30).arrayBuffer(),
    );
    if (header.byteLength !== 30 || header.getUint32(0, true) !== 0x04034b50)
      throw new Error("Invalid ZIP entry");
    const data =
      local + 30 + header.getUint16(26, true) + header.getUint16(28, true);
    if (data + bytes > file.size) throw new Error("Truncated ZIP");
    entries.set(name, file.slice(data, data + bytes));
  }
  return entries;
}
