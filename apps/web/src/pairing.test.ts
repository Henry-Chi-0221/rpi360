import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  savedPairing,
  savePairing,
  forgetPairing,
} from "../../../packages/web-sdk/src/device/pairing";

function storage() {
  const data = new Map<string, string>();
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
    removeItem: (key: string) => {
      data.delete(key);
    },
  };
}
beforeEach(() => {
  vi.stubGlobal("localStorage", storage());
  vi.stubGlobal("sessionStorage", storage());
});
afterEach(() => vi.unstubAllGlobals());

it("keeps tab-only authentication private to the tab until remembering is selected", () => {
  savePairing(" /api/ ", "test-tab-token", false);
  expect(savedPairing("/api")).toEqual({
    token: "test-tab-token",
    remembered: false,
  });
  vi.stubGlobal("sessionStorage", storage()); // a newly opened independent tab
  expect(savedPairing("/api").token).toBe("");
});

it("migrates an old session token on opt-in and reconnects from a fresh tab", () => {
  sessionStorage.setItem("rpi360-token:/api", "test-existing-token");
  const existing = savedPairing("/api");
  savePairing("/api", existing.token, true);
  vi.stubGlobal("sessionStorage", storage());
  expect(savedPairing("/api")).toEqual({
    token: existing.token,
    remembered: true,
  });
  expect(savedPairing("https://another-camera.example").token).toBe("");
  forgetPairing("/api");
  expect(savedPairing("/api").token).toBe("");
});

it("supports opting out and preserves the old session when persistent storage fails", () => {
  savePairing("/api", "test-token", true);
  savePairing("/api", "test-token", false);
  expect(localStorage.getItem("rpi360-token:/api")).toBeNull();
  vi.spyOn(localStorage, "setItem").mockImplementation(() => {
    throw new Error("quota");
  });
  expect(() => savePairing("/api", "test-token", true)).toThrow("quota");
  expect(savedPairing("/api")).toEqual({
    token: "test-token",
    remembered: false,
  });
});
