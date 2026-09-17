import {
  newProject,
  orientation,
  type ViewState,
  type EditProject,
} from "@rpi360/web-sdk";
export type Preset =
  | "reframe"
  | "planet"
  | "inverted"
  | "roll"
  | "zoom"
  | "time";
export const presets: [Preset, string, string][] = [
  ["reframe", "Keyframe reframing", "Guide the viewer’s eye"],
  ["planet", "Tiny Planet", "A world of your own"],
  ["inverted", "Inverted Tiny Planet", "Turn the horizon inside out"],
  ["roll", "Barrel Roll", "One complete, eased rotation"],
  ["zoom", "FOV Zoom", "Widen your perspective"],
  ["time", "Time Remapping", "A deliberate change of pace"],
];
export const timecode = (s: number) =>
  `${Math.floor(s / 60)
    .toString()
    .padStart(2, "0")}:${Math.floor(s % 60)
    .toString()
    .padStart(2, "0")}.${Math.floor((s % 1) * 10)}`;
export function recipe(
  id: string,
  duration: number,
  kind: Preset,
): EditProject {
  const p = newProject(id, duration);
  const view = (
    yaw: number,
    pitch: number,
    fov: number,
    projection: ViewState["projection"] = "perspective",
    spin = 0,
  ): ViewState => ({
    orientation: orientation(yaw, pitch),
    horizontal_fov_deg: fov,
    projection,
    spin_deg: spin,
  });
  let a = view(-22, 0, 90),
    b = view(22, 3, 78);
  if (kind === "planet") {
    a = view(0, -90, 170, "stereographic");
    b = view(0, -90, 310, "stereographic");
  }
  if (kind === "inverted") {
    a = view(0, 90, 170, "stereographic");
    b = view(0, 90, 310, "stereographic");
  }
  if (kind === "roll") {
    a = view(0, 0, 100);
    b = view(0, 0, 100, "perspective", 360);
  }
  if (kind === "zoom") {
    a = view(0, 0, 65);
    b = view(0, 0, 135);
  }
  const d = p.duration_us;
  p.keyframes = [
    { time_us: 0, view: a, linear: false },
    { time_us: Math.round(d * 0.15), view: a, linear: false },
    { time_us: Math.round(d * 0.85), view: b, linear: false },
    { time_us: d, view: b, linear: false },
  ];
  if (kind === "time") {
    p.keyframes = [{ time_us: 0, view: view(0, 0, 95), linear: false }];
    p.duration_us = Math.round(d * 0.65);
    p.time_remap = [
      { output_us: 0, source_us: 0 },
      { output_us: Math.round(d * 0.25), source_us: Math.round(d * 0.2) },
      { output_us: Math.round(d * 0.45), source_us: Math.round(d * 0.8) },
      { output_us: p.duration_us, source_us: d },
    ];
  }
  return p;
}
