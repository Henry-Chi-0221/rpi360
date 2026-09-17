export type Projection = "perspective" | "stereographic" | "equirectangular";
export interface ViewState {
  orientation: number[];
  horizontal_fov_deg: number;
  projection: Projection;
  spin_deg: number;
}
export interface Keyframe {
  time_us: number;
  view: ViewState;
  linear: boolean;
}
export interface EditProject {
  schema_version: 2;
  id: string;
  source_id: string;
  duration_us: number;
  keyframes: Keyframe[];
  time_remap: { output_us: number; source_us: number }[];
  alignment_us: number | null;
}
export interface Recording {
  schema_version: 2;
  id: string;
  state: string;
  calibration: string | null;
  sync?: {
    method: "libcamera-software" | "unknown";
    tolerance_us: number | null;
  };
  streams: {
    camera: number;
    path: string;
    width: number;
    height: number;
    media_start_offset_us: number;
    frames: number;
  }[];
  files: { path: string; bytes: number; sha256: string }[];
}
export const defaultView: ViewState = {
  orientation: [0, 0, 0, 1],
  horizontal_fov_deg: 90,
  projection: "perspective",
  spin_deg: 0,
};
export function newProject(source: string, duration: number): EditProject {
  return {
    schema_version: 2,
    id: crypto.randomUUID(),
    source_id: source,
    duration_us: Math.round(duration * 1e6),
    keyframes: [{ time_us: 0, view: { ...defaultView }, linear: false }],
    time_remap: [
      { output_us: 0, source_us: 0 },
      {
        output_us: Math.round(duration * 1e6),
        source_us: Math.round(duration * 1e6),
      },
    ],
    alignment_us: null,
  };
}
