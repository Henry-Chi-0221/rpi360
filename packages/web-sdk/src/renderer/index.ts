import init, {
  BrowserRenderer,
  convert_calibration,
  evaluate_project,
  orientation_from_euler,
  orientation_to_euler,
} from "../../wasm/rpi360_render.js";
import type { EditProject, ViewState } from "../types";
let ready: Promise<unknown> | undefined;
export const initCore = () => (ready ??= init());
export const evaluate = (
  project: EditProject,
  timeUs: number,
): { view: ViewState; source_time_us: number } =>
  JSON.parse(evaluate_project(JSON.stringify(project), Math.round(timeUs)));
export const orientation = (yaw: number, pitch: number, roll = 0) =>
  Array.from(orientation_from_euler(yaw, pitch, roll));
export const anglesFromOrientation = (q: number[]) =>
  Array.from(orientation_to_euler(new Float32Array(q)));
export const calibrationV2 = (value: unknown) =>
  JSON.parse(convert_calibration(JSON.stringify(value)));
export class Renderer {
  private scratch = document.createElement("canvas");
  private ctx = this.scratch.getContext("2d", { willReadFrequently: true })!;
  private constructor(
    public canvas: HTMLCanvasElement,
    private gpu: BrowserRenderer,
  ) {}
  static async create(canvas: HTMLCanvasElement, calibration: unknown) {
    await initCore();
    return new Renderer(
      canvas,
      await BrowserRenderer.create(canvas, JSON.stringify(calibration)),
    );
  }
  setCalibration(value: unknown) {
    this.gpu.set_calibration(JSON.stringify(value));
  }
  upload(source: CanvasImageSource, width: number, height: number) {
    if (this.scratch.width !== width || this.scratch.height !== height) {
      this.scratch.width = width;
      this.scratch.height = height;
    }
    this.ctx.drawImage(source, 0, 0, width, height);
    const data = this.ctx.getImageData(0, 0, width, height);
    this.gpu.upload(new Uint8Array(data.data.buffer), width, height);
  }
  draw(
    view: ViewState,
    width = this.canvas.width,
    height = this.canvas.height,
    aa = false,
  ) {
    if (this.canvas.width !== width) this.canvas.width = width;
    if (this.canvas.height !== height) this.canvas.height = height;
    this.gpu.draw(JSON.stringify(view), width, height, aa);
  }
  dispose() {
    this.gpu.free();
    this.scratch.width = this.scratch.height = 0;
  }
}
