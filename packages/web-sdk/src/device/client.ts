import type { Recording } from "../types";
export class DeviceClient {
  constructor(
    public base = "/api",
    public token = "",
  ) {
    this.base = base.replace(/\/$/, "");
  }
  async request<T = any>(
    path: string,
    body?: unknown,
    method?: string,
    signal?: AbortSignal,
  ): Promise<T> {
    const r = await fetch(this.base + path, {
      method: method ?? (body === undefined ? "GET" : "POST"),
      headers: {
        ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
    if (!r.ok) {
      let message = await r.text();
      try {
        message = JSON.parse(message).detail;
      } catch {}
      throw new Error(`${r.status}: ${message}`);
    }
    return r.json();
  }
  async pair(code: string) {
    const result = await this.request<{ token: string }>("/v1/pair", {
      code,
      name: "RPI360 Web",
    });
    this.token = result.token;
    return result;
  }
  startCapture() {
    return this.request("/v1/capture/start", {});
  }
  startRecording(requestId = crypto.randomUUID()) {
    return this.request<Recording>("/v1/recordings/start", {
      request_id: requestId,
    });
  }
  stopRecording(requestId = crypto.randomUUID()) {
    return this.request<Recording>("/v1/recordings/stop", {
      request_id: requestId,
    });
  }
  async preview(
    video: HTMLVideoElement,
    onDiagnostics: (v: any) => void = () => {},
  ) {
    const pc = new RTCPeerConnection({ iceServers: [] });
    const channel = pc.createDataChannel("frames", {
      ordered: false,
      maxRetransmits: 0,
    });
    channel.onmessage = (e) => {
      try {
        onDiagnostics(JSON.parse(e.data));
      } catch {}
    };
    pc.addTransceiver("video", { direction: "recvonly" });
    pc.ontrack = (e) => {
      video.srcObject = new MediaStream([e.track]);
      void video.play().catch(() => {});
    };
    let id: string | undefined;
    try {
      await pc.setLocalDescription(await pc.createOffer());
      if (pc.iceGatheringState !== "complete")
        await new Promise<void>((resolve, reject) => {
          const timer = setTimeout(
            () => reject(new Error("ICE gathering timed out")),
            10000,
          );
          pc.addEventListener("icegatheringstatechange", () => {
            if (pc.iceGatheringState === "complete") {
              clearTimeout(timer);
              resolve();
            }
          });
        });
      const answer = await this.request<{
        id: string;
        sdp: string;
        type: "answer";
      }>("/v1/preview-sessions", pc.localDescription?.toJSON());
      id = answer.id;
      await pc.setRemoteDescription(answer);
      await new Promise<void>((resolve, reject) => {
        if (video.readyState >= 2) {
          resolve();
          return;
        }
        const timer = setTimeout(() => {
          video.removeEventListener("loadeddata", ready);
          reject(
            new Error(
              "Preview connected but no decodable video arrived; check the negotiated H.264 mode",
            ),
          );
        }, 15000);
        const ready = () => {
          clearTimeout(timer);
          resolve();
        };
        video.addEventListener("loadeddata", ready, { once: true });
      });
      return {
        pc,
        close: async () => {
          pc.close();
          video.srcObject = null;
          if (id)
            await this.request(
              "/v1/preview-sessions/" + id,
              undefined,
              "DELETE",
            );
        },
      };
    } catch (e) {
      pc.close();
      if (id)
        await this.request(
          "/v1/preview-sessions/" + id,
          undefined,
          "DELETE",
        ).catch(() => {});
      throw e;
    }
  }
}
