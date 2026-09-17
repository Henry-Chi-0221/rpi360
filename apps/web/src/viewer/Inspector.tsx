import { Aperture, ArrowUpRight, Globe2, RotateCcw } from "lucide-react";
import type { ViewState } from "@rpi360/web-sdk";
import type { Preset } from "../editor/presets";
interface Props {
  view: ViewState;
  angles: number[];
  ratio: string;
  effect: Preset;
  alignment: string;
  unknownAlignment: boolean;
  onManual(
    angles: number[],
    fov?: number,
    projection?: ViewState["projection"],
  ): void;
  onRatio(ratio: string): void;
  onEffect(effect: Preset): void;
  onEffects(): void;
  onAlignment(value: string): void;
}
export function Inspector({
  view,
  angles,
  ratio,
  effect,
  alignment,
  unknownAlignment,
  onManual,
  onRatio,
  onEffect,
  onEffects,
  onAlignment,
}: Props) {
  return (
    <aside className="inspector">
      <div className="panel-heading">
        <h2>View settings</h2>
        <button
          className="icon"
          aria-label="Reset viewpoint"
          onClick={() => onManual([0, 0, 0], 90, "perspective")}
        >
          <RotateCcw size={14} />
        </button>
      </div>
      <div className="field-label">Projection</div>
      <select
        aria-label="Projection"
        value={view.projection}
        onChange={(e) =>
          onManual(
            angles,
            Math.min(view.horizontal_fov_deg, 170),
            e.target.value as ViewState["projection"],
          )
        }
      >
        <option value="perspective">Perspective</option>
        <option value="stereographic">Stereographic</option>
        <option value="equirectangular">Equirectangular</option>
      </select>
      <div className="field-label fov-label">
        Field of view <strong>{Math.round(view.horizontal_fov_deg)}°</strong>
      </div>
      <input
        aria-label="Field of view"
        type="range"
        min="25"
        max={view.projection === "perspective" ? 170 : 340}
        value={view.horizontal_fov_deg}
        onChange={(e) => onManual(angles, +e.target.value)}
      />
      <div className="range-labels">
        <span>Narrow</span>
        <span>Wide</span>
      </div>
      <div className="divider" />
      <div className="field-label">Orientation</div>
      <div className="orientation-grid">
        {["Yaw", "Pitch", "Roll"].map((label, i) => (
          <label key={label}>
            {label}
            <div>
              <input
                aria-label={label}
                type="number"
                min={i === 1 ? -90 : -360}
                max={i === 1 ? 90 : 360}
                value={Math.round(angles[i])}
                onChange={(e) => {
                  const a = [...angles];
                  a[i] = Math.max(
                    i === 1 ? -90 : -360,
                    Math.min(i === 1 ? 90 : 360, +e.target.value),
                  );
                  onManual(a);
                }}
              />
              <span>°</span>
            </div>
          </label>
        ))}
      </div>
      <p className="hint">
        Adjust your view, then add a keyframe to save the camera position.
      </p>
      <div className="divider" />
      <div className="field-label">Canvas ratio</div>
      <div className="ratios">
        {["16:9", "9:16", "1:1"].map((r) => (
          <button
            className={ratio === r ? "selected" : ""}
            key={r}
            onClick={() => onRatio(r)}
          >
            <i style={{ aspectRatio: r.replace(":", "/") }} />
            {r}
          </button>
        ))}
      </div>
      <div className="divider" />
      <div className="field-label">
        Quick effects{" "}
        <button className="text-link" onClick={() => onEffects()}>
          View all <ArrowUpRight size={12} />
        </button>
      </div>
      <div className="quick-effects">
        <button
          className={effect === "reframe" ? "selected" : ""}
          onClick={() => onEffect("reframe")}
        >
          <Aperture size={18} />
          Reframe
        </button>
        <button
          className={effect === "planet" ? "selected" : ""}
          onClick={() => onEffect("planet")}
        >
          <Globe2 size={18} />
          Tiny Planet
        </button>
      </div>
      {unknownAlignment && (
        <div className="alignment">
          <label>
            Source alignment correction (ms)
            <input
              type="number"
              value={alignment}
              onChange={(e) => onAlignment(e.target.value)}
            />
          </label>
        </div>
      )}
      <div className="inspector-bottom">
        <span className="status-dot" />
        Rendering on your device
        <small>FOV and orientation never leave this screen.</small>
      </div>
    </aside>
  );
}
