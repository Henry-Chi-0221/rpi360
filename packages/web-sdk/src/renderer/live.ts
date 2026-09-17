import { DeviceClient } from "../device/client";
import { defaultView, type Projection, type ViewState } from "../types";
import { Renderer, orientation } from "./index";

export interface LiveViewOptions {
  yaw?: number;
  pitch?: number;
  roll?: number;
  fov?: number;
  projection?: Projection;
}

/** One paired stream, one GPU renderer. View changes stay entirely on the client. */
export class LiveViewer {
  private frame = 0;
  private stopped = false;
  private lastTime = -1;
  private angles = { yaw: 0, pitch: 0, roll: 0 };
  private view: ViewState = { ...defaultView };
  private constructor(
    private renderer: Renderer,
    private video: HTMLVideoElement,
    private session: Awaited<ReturnType<DeviceClient["preview"]>>,
    private onError: (error: unknown) => void,
  ) {}

  static async connect(
    canvas: HTMLCanvasElement,
    camera: DeviceClient,
    options: LiveViewOptions & {
      onDiagnostics?: (value: unknown) => void;
      onError?: (error: unknown) => void;
    } = {},
  ) {
    const { profile } = await camera.request<{ profile: unknown }>(
      "/v1/calibration",
    );
    if (!profile)
      throw new Error("The camera needs a calibration profile for VR preview.");
    const renderer = await Renderer.create(canvas, profile);
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    let session: Awaited<ReturnType<DeviceClient["preview"]>> | undefined;
    try {
      session = await camera.preview(video, options.onDiagnostics);
      const viewer = new LiveViewer(
        renderer,
        video,
        session,
        options.onError ?? console.error,
      );
      viewer.setView(options);
      viewer.drawCurrentFrame();
      viewer.frame = requestAnimationFrame(viewer.tick);
      return viewer;
    } catch (error) {
      await session?.close().catch(() => {});
      video.srcObject = null;
      renderer.dispose();
      throw error;
    }
  }

  /** Degrees; FOV is horizontal. Redraws the current frame without a network request. */
  setView(options: LiveViewOptions) {
    if (this.stopped) throw new Error("This viewer has been closed.");
    for (const value of [options.yaw, options.pitch, options.roll, options.fov])
      if (value !== undefined && !Number.isFinite(value))
        throw new Error("View angles must be finite.");
    const projection = options.projection ?? this.view.projection;
    const fov = options.fov ?? this.view.horizontal_fov_deg;
    if (
      projection !== "equirectangular" &&
      (fov <= 0 || fov >= (projection === "stereographic" ? 360 : 180))
    )
      throw new Error(
        "FOV must be between 0 and 180 degrees (360 for stereographic).",
      );
    this.angles = {
      yaw: options.yaw ?? this.angles.yaw,
      pitch: options.pitch ?? this.angles.pitch,
      roll: options.roll ?? this.angles.roll,
    };
    this.view = {
      ...this.view,
      projection,
      horizontal_fov_deg: fov,
      orientation: orientation(
        this.angles.yaw,
        this.angles.pitch,
        this.angles.roll,
      ),
    };
    if (this.lastTime >= 0) this.renderer.draw(this.view);
  }

  private drawCurrentFrame() {
    if (
      this.video.readyState >= 2 &&
      this.lastTime !== this.video.currentTime
    ) {
      this.renderer.upload(
        this.video,
        this.video.videoWidth,
        this.video.videoHeight,
      );
      this.lastTime = this.video.currentTime;
      this.renderer.draw(this.view);
    }
  }

  private tick = () => {
    if (this.stopped) return;
    try {
      this.drawCurrentFrame();
      this.frame = requestAnimationFrame(this.tick);
    } catch (error) {
      void this.close().catch(this.onError);
      this.onError(error);
    }
  };

  /** Closes only this preview. An active recording continues on the Pi. */
  async close() {
    if (this.stopped) return;
    this.stopped = true;
    cancelAnimationFrame(this.frame);
    this.renderer.dispose();
    await this.session.close();
  }
}
