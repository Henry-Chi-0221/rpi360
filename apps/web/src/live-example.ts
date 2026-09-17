import { DeviceClient, LiveViewer } from "@rpi360/web-sdk";

const camera = new DeviceClient(import.meta.env.DEV ? "/api" : location.origin);
const tokenKey = "rpi360-token:" + camera.base;
camera.token = sessionStorage.getItem(tokenKey) ?? "";
const canvas = document.querySelector<HTMLCanvasElement>("#view")!;
const start = document.querySelector<HTMLButtonElement>("#start")!;
const stop = document.querySelector<HTMLButtonElement>("#stop")!;
const status = document.querySelector<HTMLOutputElement>("#status")!;
let viewer: LiveViewer | undefined;

document.querySelector<HTMLFormElement>("#connect")!.onsubmit = async (
  event,
) => {
  event.preventDefault();
  start.disabled = true;
  status.textContent = "Connecting…";
  try {
    const code = document
      .querySelector<HTMLInputElement>("#code")!
      .value.trim();
    if (code) {
      await camera.pair(code);
      sessionStorage.setItem(tokenKey, camera.token);
    }
    viewer = await LiveViewer.connect(canvas, camera, {
      onError: (error) => {
        status.textContent = String(error);
        stop.disabled = true;
        start.disabled = false;
      },
    });
    status.textContent = "Live · change FOV, yaw, or pitch below";
    stop.disabled = false;
  } catch (error) {
    status.textContent = String(error);
    start.disabled = false;
  }
};
stop.onclick = async () => {
  stop.disabled = true;
  try {
    await viewer?.close();
    status.textContent = "Preview closed. Recording is independent.";
  } catch (error) {
    status.textContent = String(error);
  } finally {
    viewer = undefined;
    start.disabled = false;
  }
};
for (const name of ["fov", "yaw", "pitch"] as const) {
  const slider = document.querySelector<HTMLInputElement>("#" + name)!;
  slider.oninput = () => viewer?.setView({ [name]: slider.valueAsNumber });
}
window.addEventListener("pagehide", () => {
  void viewer?.close().catch(() => {});
});
