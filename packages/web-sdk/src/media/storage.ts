import { createSHA256 } from "hash-wasm";
import type { EditProject, Recording } from "../types";
import type { DeviceClient } from "../device/client";
async function database() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open("rpi360", 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore("projects", { keyPath: "id" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
export async function saveProject(project: EditProject) {
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction("projects", "readwrite");
      tx.objectStore("projects").put(project);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}
export async function projects(): Promise<EditProject[]> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const r = db.transaction("projects").objectStore("projects").getAll();
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    });
  } finally {
    db.close();
  }
}
export async function quota(bytes: number) {
  const q = await navigator.storage.estimate();
  if (q.quota !== undefined && bytes > q.quota - (q.usage ?? 0))
    throw new Error(
      "Not enough browser storage. Remove downloaded or exported files first.",
    );
}
export async function mediaDirectory() {
  const root = await navigator.storage.getDirectory();
  return root.getDirectoryHandle("rpi360-media", { create: true });
}
export async function downloadRecording(
  device: DeviceClient,
  recording: Recording,
  onProgress: (n: number) => void,
  signal: AbortSignal,
) {
  await quota(recording.files.reduce((n, f) => n + f.bytes, 0));
  const root = await mediaDirectory();
  const dir = await root.getDirectoryHandle(recording.id, { create: true });
  let done = 0;
  const total = recording.files.reduce((n, f) => n + f.bytes, 0);
  for (const entry of recording.files) {
    if (!/^[a-zA-Z0-9_.-]+$/.test(entry.path))
      throw new Error("Unsafe recording filename");
    signal.throwIfAborted();
    const handle = await dir.getFileHandle(entry.path, { create: true });
    const existing = await handle.getFile();
    let offset = existing.size;
    if (offset > entry.bytes) offset = 0;
    if (offset < entry.bytes) {
      const r = await fetch(
        `${device.base}/v1/recordings/${recording.id}/files/${entry.path}`,
        {
          headers: {
            Authorization: `Bearer ${device.token}`,
            Range: `bytes=${offset}-`,
          },
          signal,
        },
      );
      if (!r.ok || !r.body) throw new Error("Download failed");
      if (offset && r.status !== 206) offset = 0;
      const writer = await handle.createWritable({
        keepExistingData: offset > 0,
      });
      await writer.seek(offset);
      const reader = r.body.getReader();
      try {
        while (true) {
          signal.throwIfAborted();
          const { done: end, value } = await reader.read();
          if (end) break;
          await writer.write(value);
          offset += value.length;
          onProgress((done + offset) / total);
        }
        await writer.close();
      } catch (e) {
        await writer.close();
        await reader.cancel();
        throw e;
      }
    }
    const file = await handle.getFile();
    const h = await createSHA256();
    for (let p = 0; p < file.size; p += 1024 * 1024) {
      signal.throwIfAborted();
      h.update(
        new Uint8Array(await file.slice(p, p + 1024 * 1024).arrayBuffer()),
      );
    }
    if (file.size !== entry.bytes || h.digest() !== entry.sha256) {
      await dir.removeEntry(entry.path);
      throw new Error("Downloaded checksum mismatch; retry the file");
    }
    done += entry.bytes;
  }
  const manifest = await dir.getFileHandle("manifest.json", { create: true });
  const w = await manifest.createWritable();
  await w.write(JSON.stringify(recording));
  await w.close();
  return localRecording(recording.id);
}
export async function localRecording(id: string) {
  const dir = await (await mediaDirectory()).getDirectoryHandle(id);
  const files = new Map<string, Blob>();
  for await (const [name, handle] of dir as any) {
    if (handle.kind === "file") files.set(name, await handle.getFile());
  }
  return files;
}
export async function localRecordings(): Promise<string[]> {
  const ids: string[] = [];
  for await (const [name, handle] of (await mediaDirectory()) as any) {
    if (handle.kind === "directory") {
      try {
        await handle.getFileHandle("manifest.json");
        ids.push(name);
      } catch {}
    }
  }
  return ids;
}
export async function removeRecording(id: string) {
  await (await mediaDirectory()).removeEntry(id, { recursive: true });
}
