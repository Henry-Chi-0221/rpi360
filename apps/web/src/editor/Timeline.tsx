import { Diamond, Pause, Play, Trash2 } from "lucide-react";
import type { EditProject } from "@rpi360/web-sdk";
import { timecode } from "./presets";
interface Props {
  project: EditProject | null;
  time: number;
  playing: boolean;
  disabled: boolean;
  poster?: string;
  onPlay(): void;
  onSeek(time: number): void;
  onAdd(): void;
  onDelete(timeUs: number): void;
}
export function Timeline({
  project,
  time,
  playing,
  disabled,
  poster,
  onPlay,
  onSeek,
  onAdd,
  onDelete,
}: Props) {
  const duration = (project?.duration_us ?? 8000000) / 1e6;
  const selected = project?.keyframes.find(
    (k) => Math.abs(k.time_us - time * 1e6) < 10000,
  );
  return (
    <div className="timeline">
      <div className="transport">
        <button
          className="play"
          aria-label={playing ? "Pause" : "Play edit"}
          disabled={disabled || !project}
          onClick={onPlay}
        >
          {playing ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <strong>{timecode(time)}</strong>
        <span>/ {timecode(duration)}</span>
        <div className="transport-spacer" />
        <button
          className="subtle"
          onClick={onAdd}
          disabled={disabled || !project}
        >
          <Diamond size={13} />
          Add keyframe
        </button>
        <button
          className="icon"
          aria-label="Delete selected keyframe"
          onClick={() => selected && onDelete(selected.time_us)}
          disabled={disabled || !selected || selected.time_us === 0}
        >
          <Trash2 size={14} />
        </button>
      </div>
      <div className="ruler">
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <span key={f}>{timecode(f * duration)}</span>
        ))}
      </div>
      <div className="timeline-track">
        <div
          className="clip-strip"
          style={{ backgroundImage: poster ? `url(${poster})` : undefined }}
        />
        <input
          aria-label="Timeline position"
          type="range"
          min="0"
          max={duration}
          step=".01"
          value={time}
          disabled={disabled}
          onChange={(e) => onSeek(+e.target.value)}
        />
        {project?.keyframes.map((k) => (
          <button
            disabled={disabled}
            aria-label={`Keyframe at ${timecode(k.time_us / 1e6)}`}
            className="keyframe-dot"
            key={k.time_us}
            style={{ left: `${(k.time_us / project.duration_us) * 100}%` }}
            onClick={() => onSeek(k.time_us / 1e6)}
          >
            <Diamond size={12} fill="currentColor" />
          </button>
        ))}
      </div>
      <div className="timeline-footer">
        <span>
          <Diamond size={11} />
          {project?.keyframes.length ?? 0} keyframes
        </span>
        <span>Smooth interpolation</span>
      </div>
    </div>
  );
}
