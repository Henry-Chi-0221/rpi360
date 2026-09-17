import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveViewer } from "../../../packages/web-sdk/src/renderer/live";
import { DeviceClient } from "../../../packages/web-sdk/src/device/client";

const gpu = vi.hoisted(() => ({
  upload: vi.fn(),
  draw: vi.fn(),
  dispose: vi.fn(),
}));
vi.mock("../../../packages/web-sdk/src/renderer/index", () => ({
  Renderer: { create: vi.fn(async () => gpu) },
  orientation: () => [0, 0, 0, 1],
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("document", {
    createElement: () => ({
      readyState: 2,
      currentTime: 1,
      videoWidth: 1440,
      videoHeight: 540,
    }),
  });
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn(() => 42),
  );
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});
afterEach(() => vi.unstubAllGlobals());

describe("simple live API lifecycle", () => {
  it("connects a fresh client without credentials or a pairing request", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_mode: "local" })),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ control_policy: "shared" })),
      );
    vi.stubGlobal("fetch", fetch);
    await expect(new DeviceClient().connect()).resolves.toEqual({
      access_mode: "local",
    });
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/info",
      "/api/v1/capabilities",
    ]);
    expect(
      fetch.mock.calls.every(
        ([, options]) => !("Authorization" in options.headers),
      ),
    ).toBe(true);
  });

  it("explains how to upgrade an older Pi service", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response('{"paired":true}')),
    );
    await expect(new DeviceClient().connect()).rejects.toThrow(
      "Update the Pi camera service",
    );
  });

  it("changes FOV locally and closes preview exactly once without stopping recording", async () => {
    const camera = new DeviceClient();
    const request = vi
      .spyOn(camera, "request")
      .mockResolvedValue({ profile: { schema_version: 2 } });
    const close = vi.fn(async () => {});
    vi.spyOn(camera, "preview").mockResolvedValue({
      pc: {} as RTCPeerConnection,
      close,
    });
    const viewer = await LiveViewer.connect({} as HTMLCanvasElement, camera);
    const calls = request.mock.calls.length;
    viewer.setView({ fov: 120, yaw: 20 });
    expect(gpu.draw).toHaveBeenLastCalledWith(
      expect.objectContaining({ horizontal_fov_deg: 120 }),
    );
    expect(request.mock.calls).toHaveLength(calls);
    expect(() => viewer.setView({ fov: Number.NaN })).toThrow("finite");
    await viewer.close();
    await viewer.close();
    expect(close).toHaveBeenCalledTimes(1);
    expect(gpu.dispose).toHaveBeenCalledTimes(1);
    expect(cancelAnimationFrame).toHaveBeenCalledWith(42);
    expect(
      request.mock.calls.some(([path]) => path.includes("recordings")),
    ).toBe(false);
  });

  it("releases the GPU when WebRTC negotiation fails", async () => {
    const camera = new DeviceClient();
    vi.spyOn(camera, "request").mockResolvedValue({ profile: {} });
    vi.spyOn(camera, "preview").mockRejectedValue(new Error("viewer limit"));
    await expect(
      LiveViewer.connect({} as HTMLCanvasElement, camera),
    ).rejects.toThrow("viewer limit");
    expect(gpu.dispose).toHaveBeenCalledTimes(1);
    expect(requestAnimationFrame).not.toHaveBeenCalled();
  });

  it("explains an unavailable SSH proxy and preserves server errors", async () => {
    const client = new DeviceClient();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("", { status: 500 })),
    );
    await expect(client.request("/v1/info")).rejects.toThrow("make preview");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response('{"detail":"API token required"}', { status: 401 }),
        ),
    );
    await expect(client.request("/v1/info")).rejects.toThrow(
      "401: API token required",
    );
  });
});
