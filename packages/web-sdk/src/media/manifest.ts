import type { Recording } from "../types";

// Validate the boundaries needed before opening media or allocating decoder state.
// The complete interchange contract is schemas/recording.schema.json.
export async function readManifest(blob: Blob): Promise<Recording> {
  if (blob.size > 1024 * 1024)
    throw new Error("Recording manifest exceeds 1 MiB");
  const value = JSON.parse(await blob.text());
  if (
    value?.schema_version !== 2 ||
    !["complete", "recovered"].includes(value.state)
  )
    throw new Error(
      "Recording is unfinished or unsupported; recover it before importing",
    );
  if (
    !/^[a-f0-9]{32}$/.test(value.id) ||
    value.clock?.unit !== "microseconds" ||
    !Array.isArray(value.streams) ||
    value.streams.length !== 2 ||
    !Array.isArray(value.files) ||
    value.files.length > 4096
  )
    throw new Error("Invalid recording manifest");
  const paths = new Set<string>();
  for (const file of value.files) {
    if (
      !file ||
      typeof file.path !== "string" ||
      !/^[a-zA-Z0-9_-][a-zA-Z0-9_.-]*$/.test(file.path) ||
      paths.has(file.path) ||
      !Number.isSafeInteger(file.bytes) ||
      file.bytes < 0 ||
      !/^[a-f0-9]{64}$/.test(file.sha256)
    )
      throw new Error("Invalid or duplicate checksum entry");
    paths.add(file.path);
  }
  const streams = [...value.streams].sort((a, b) => a.camera - b.camera);
  for (const [camera, stream] of streams.entries()) {
    if (
      stream.camera !== camera ||
      stream.path !== `camera${camera}.mp4` ||
      stream.codec !== "h264" ||
      !Number.isSafeInteger(stream.media_start_offset_us) ||
      !Number.isSafeInteger(stream.width) ||
      stream.width <= 0 ||
      !Number.isSafeInteger(stream.height) ||
      stream.height <= 0 ||
      !paths.has(stream.path)
    )
      throw new Error("Invalid camera track or missing source checksum");
  }
  if (
    value.calibration !== null &&
    (typeof value.calibration !== "string" || !paths.has(value.calibration))
  )
    throw new Error("Calibration checksum missing");
  return value as Recording;
}
