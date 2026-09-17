#!/usr/bin/env node
import { fileURLToPath } from "node:url";
import { managePreview } from "./preview-service.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const [first, second] = process.argv.slice(2);
if (process.platform !== "darwin" || first === "--foreground") {
  if (["status", "stop", "authorize"].includes(first)) {
    console.error("Background service management currently requires macOS.");
    process.exit(2);
  }
  process.argv = [
    process.argv[0],
    process.argv[1],
    first === "--foreground" ? second : first,
  ];
  await import("./preview-foreground.mjs");
} else {
  try {
    const action = ["start", "status", "stop", "authorize"].includes(first)
      ? first
      : "start";
    await managePreview({
      root,
      action,
      camera: action === first ? second : first,
    });
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
