import { Inspector } from "./viewer/Inspector";
import { presets, recipe, timecode, type Preset } from "./editor/presets";
import { downloadBlob } from "./export/download";
import { Timeline } from "./editor/Timeline";
import { useEffect, useRef, useState } from "react";
import {
  Aperture,
  ArrowDownToLine,
  ArrowUpRight,
  Camera,
  Check,
  ChevronDown,
  CircleHelp,
  Clapperboard,
  Diamond,
  FolderOpen,
  Globe2,
  Layers,
  Link2,
  LoaderCircle,
  Maximize2,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Save,
  Settings2,
  Trash2,
  Video,
  Wifi,
  X,
} from "lucide-react";
import {
  DeviceClient,
  DeviceApiError,
  Renderer,
  RecordedSource,
  StillSource,
  initCore,
  evaluate,
  orientation,
  anglesFromOrientation,
  newProject,
  defaultView,
  saveProject,
  projects,
  localRecordings,
  localRecording,
  removeRecording,
  downloadRecording,
  exportVideo,
  type EditProject,
  type PairSource,
  type ViewState,
  type Recording,
} from "@rpi360/web-sdk";

type Demo = {
  id: string;
  title: string;
  image: string;
  kind: string;
  source_pts_seconds: number[];
};
export default function App() {
  const [downloadReady, setDownloadReady] = useState<{
    url: string;
    name: string;
  } | null>(null);
  const exportCleanup = useRef<(() => void) | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null),
    rawCanvas = useRef<HTMLCanvasElement>(null),
    video = useRef<HTMLVideoElement>(null),
    renderer = useRef<Renderer | null>(null),
    source = useRef<PairSource | null>(null),
    live = useRef<{ pc: RTCPeerConnection; close(): Promise<void> } | null>(
      null,
    );
  const projectRef = useRef<EditProject | null>(null),
    viewRef = useRef<ViewState>(defaultView),
    busyFrame = useRef(false),
    clock = useRef(0),
    abort = useRef<AbortController | null>(null),
    fileInput = useRef<HTMLInputElement>(null),
    folderInput = useRef<HTMLInputElement>(null),
    projectInput = useRef<HTMLInputElement>(null);
  const [catalog, setCatalog] = useState<Demo[]>([]),
    [active, setActive] = useState("lake"),
    [title, setTitle] = useState("Still water, open sky"),
    [sourceKind, setSourceKind] = useState("360 still-frame reframing"),
    [project, setProject] = useState<EditProject | null>(null),
    [saved, setSaved] = useState<EditProject[]>([]),
    [localIds, setLocalIds] = useState<string[]>([]);
  const [view, setView] = useState<ViewState>(defaultView),
    [angles, setAngles] = useState([0, 0, 0]),
    [time, setTime] = useState(0),
    [playing, setPlaying] = useState(false),
    [mode, setMode] = useState("view"),
    [spherical, setSpherical] = useState(false),
    [ratio, setRatio] = useState("16:9"),
    [effect, setEffect] = useState<Preset>("reframe"),
    [tab, setTab] = useState("library");
  const [message, setMessage] = useState("Loading the shared renderer…"),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [progress, setProgress] = useState<number | null>(null),
    [dialog, setDialog] = useState<"device" | "export" | null>(null),
    [device, setDevice] = useState<DeviceClient | null>(null),
    [url, setUrl] = useState(import.meta.env.DEV ? "/api" : location.origin),
    [apiToken, setApiToken] = useState(""),
    [needsToken, setNeedsToken] = useState(false),
    [connecting, setConnecting] = useState(false),
    [status, setStatus] = useState<any>(null),
    [remote, setRemote] = useState<Recording[]>([]),
    [diagnostics, setDiagnostics] = useState<any>(null),
    [liveOn, setLiveOn] = useState(false),
    [alignment, setAlignment] = useState("0");
  const size =
    ratio === "9:16"
      ? [720, 1280]
      : ratio === "1:1"
        ? [960, 960]
        : ratio === "2:1"
          ? [1440, 720]
          : [1280, 720];
  const sizeRef = useRef(size),
    modeRef = useRef(mode);
  sizeRef.current = size;
  modeRef.current = mode;
  const fail = (e: unknown) => {
    setError(e instanceof Error ? e.message : String(e));
    setLoading(false);
    setPlaying(false);
  };
  function updateProject(p: EditProject) {
    projectRef.current = p;
    setProject(p);
  }
  function draw(v: ViewState) {
    viewRef.current = v;
    setView(v);
    const a = anglesFromOrientation(v.orientation);
    a[2] += v.spin_deg;
    setAngles(a);
    const [w, h] = sizeRef.current;
    renderer.current?.draw(
      modeRef.current === "panorama"
        ? {
            ...v,
            orientation: [0, 0, 0, 1],
            spin_deg: 0,
            projection: "equirectangular",
          }
        : v,
      modeRef.current === "panorama" ? 1440 : w,
      modeRef.current === "panorama" ? 720 : h,
    );
  }
  async function frameAt(t: number, p = projectRef.current) {
    if (!source.current || !renderer.current || !p || busyFrame.current) return;
    busyFrame.current = true;
    try {
      const e = evaluate(p, t * 1e6),
        pair = await source.current.frame(
          e.source_time_us / 1e6,
          p.alignment_us,
        );
      renderer.current.upload(pair.canvas, pair.width, pair.height);
      const raw = rawCanvas.current;
      if (raw) {
        raw.width = pair.width;
        raw.height = pair.height;
        raw.getContext("2d")!.drawImage(pair.canvas, 0, 0);
      }
      draw(e.view);
      setTime(t);
      setDiagnostics({ delta_us: pair.deltaUs });
    } finally {
      busyFrame.current = false;
    }
  }
  const exporting = useRef(false);
  async function attach(
    s: PairSource,
    name: string,
    kind: string,
    preset: Preset = "reframe",
  ) {
    if (exporting.current) {
      s.dispose();
      return;
    }
    setPlaying(false);
    setError("");
    setLoading(true);
    await live.current?.close();
    live.current = null;
    setLiveOn(false);
    source.current?.dispose();
    source.current = s;
    setTitle(name);
    setSourceKind(kind);
    if (!renderer.current)
      renderer.current = await Renderer.create(canvas.current!, s.calibration);
    else renderer.current.setCalibration(s.calibration);
    const p = recipe(s.id, Math.min(s.duration, 30), preset);
    if (s.alignmentKnown) p.alignment_us = 0;
    updateProject(p);
    setActive(s.id);
    setEffect(preset);
    clock.current = 0;
    await frameAt(0.08, p);
    setLoading(false);
    setMessage(
      s.alignmentKnown
        ? "Ready · source timing preserved"
        : "Source clock alignment is unknown",
    );
  }
  async function loadDemo(d: Demo) {
    if (progress !== null || (loading && source.current)) return;
    setLoading(true);
    await initCore();
    const [cal, image] = await Promise.all([
      fetch("/demo/calibration.json").then((r) => r.json()),
      createImageBitmap(await fetch(d.image).then((r) => r.blob())),
    ]);
    const packed = document.createElement("canvas");
    packed.width = image.width;
    packed.height = image.height;
    packed.getContext("2d")!.drawImage(image, 0, 0);
    image.close();
    await attach(new StillSource(d.id, cal, packed), d.title, d.kind);
  }
  useEffect(() => {
    let disposed = false;
    (async () => {
      try {
        await initCore();
        const items = await fetch("/demo/catalog.json").then((r) => r.json());
        if (disposed) return;
        setCatalog(items);
        await loadDemo(items[0]);
        setSaved(await projects());
        setLocalIds(await localRecordings());
      } catch (e) {
        if (!disposed) fail(e);
      }
    })();
    return () => {
      disposed = true;
      abort.current?.abort();
      exportCleanup.current?.();
      source.current?.dispose();
      source.current = null;
      renderer.current?.dispose();
      renderer.current = null;
      void live.current?.close();
      live.current = null;
    };
  }, []);
  useEffect(() => {
    if (device) return;
    const controller = new AbortController();
    for (const name of ["localStorage", "sessionStorage"] as const) {
      try {
        const storage = window[name];
        for (let i = storage.length - 1; i >= 0; i--) {
          const key = storage.key(i);
          if (key?.startsWith("rpi360-token:")) storage.removeItem(key);
        }
      } catch {
        /* Storage is optional. */
      }
    }
    const client = new DeviceClient(
      import.meta.env.DEV ? "/api" : location.origin,
    );
    let busy = false;
    const probe = async () => {
      if (busy || controller.signal.aborted) return;
      busy = true;
      try {
        const info = await client.request<{ access_mode: string }>(
          "/v1/info",
          undefined,
          undefined,
          controller.signal,
        );
        if (info.access_mode !== "local") return;
        await client.request(
          "/v1/capabilities",
          undefined,
          undefined,
          controller.signal,
        );
        const recordings = await client.request(
          "/v1/recordings",
          undefined,
          undefined,
          controller.signal,
        );
        if (!controller.signal.aborted) {
          setRemote(recordings.items);
          setDevice(client);
        }
      } catch {
        /* Retry quietly while camera-free editing stays available. */
      } finally {
        busy = false;
      }
    };
    void probe();
    const timer = setInterval(probe, 5000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [device]);
  useEffect(() => {
    if (renderer.current)
      try {
        draw(viewRef.current);
      } catch (e) {
        fail(e);
      }
  }, [ratio, mode]);
  useEffect(() => {
    if (!playing) return;
    let id = 0,
      stopped = false;
    let last = performance.now();
    const tick = async (now: number) => {
      if (stopped) return;
      const dt = (now - last) / 1000;
      last = now;
      if (!document.hidden) {
        clock.current += Math.min(dt, 0.15);
        const end = (projectRef.current?.duration_us ?? 0) / 1e6;
        if (clock.current >= end) {
          clock.current = end;
          setPlaying(false);
        }
        try {
          await frameAt(clock.current);
        } catch (e) {
          fail(e);
        }
      }
      if (!stopped) id = requestAnimationFrame(tick);
    };
    id = requestAnimationFrame(tick);
    return () => {
      stopped = true;
      cancelAnimationFrame(id);
    };
  }, [playing]);
  useEffect(() => {
    if (!device) return;
    let stopped = false;
    let disconnected = false;
    const poll = async () => {
      try {
        const s = await device.request("/v1/status");
        if (!stopped) {
          setStatus(s);
          if (disconnected)
            setMessage("Camera reconnected · preview controls are available");
          disconnected = false;
        }
      } catch (e) {
        if (!stopped) {
          setStatus(null);
          if (!disconnected)
            setMessage("Device disconnected · local editing is available");
          disconnected = true;
        }
      }
    };
    void poll();
    const id = setInterval(poll, 2000);
    return () => {
      stopped = true;
      clearInterval(id);
    };
  }, [device]);
  useEffect(() => {
    if (!liveOn || !video.current) return;
    let stopped = false,
      callback = 0;
    const v = video.current;
    const tick = () => {
      if (stopped) return;
      try {
        if (v.readyState >= 2 && renderer.current) {
          renderer.current.upload(v, v.videoWidth, v.videoHeight);
          const r = rawCanvas.current!;
          r.width = v.videoWidth;
          r.height = v.videoHeight;
          r.getContext("2d")!.drawImage(v, 0, 0);
          draw(viewRef.current);
        }
      } catch (e) {
        fail(e);
      }
      callback = v.requestVideoFrameCallback(tick);
    };
    callback = v.requestVideoFrameCallback(tick);
    return () => {
      stopped = true;
      v.cancelVideoFrameCallback(callback);
    };
  }, [liveOn]);
  async function importFiles(files: File[]) {
    if (progress !== null || loading) return;
    if (!files.length) return;
    setLoading(true);
    setMessage("Validating source files…");
    try {
      abort.current = new AbortController();
      const s = await RecordedSource.open(files, abort.current.signal);
      await attach(
        s,
        files[0].name.replace(/\.r360.*$/, ""),
        "Recorded dual fisheye",
      );
    } catch (e) {
      fail(e);
    }
  }
  function manual(
    a: number[],
    fov = view.horizontal_fov_deg,
    projection = view.projection,
  ) {
    setPlaying(false);
    setAngles(a);
    draw({
      orientation: orientation(...(a as [number, number, number])),
      horizontal_fov_deg: fov,
      projection,
      spin_deg: 0,
    });
  }
  function addKeyframe() {
    if (!project) return;
    const t = Math.round(time * 1e6);
    const keys = project.keyframes.filter(
      (k) => Math.abs(k.time_us - t) > 10000,
    );
    keys.push({ time_us: t, view: { ...viewRef.current }, linear: false });
    keys.sort((a, b) => a.time_us - b.time_us);
    updateProject({ ...project, keyframes: keys });
    setMessage("Keyframe added · smooth interpolation");
  }
  function applyPreset(kind: Preset) {
    if (progress !== null || liveOn) return;
    if (!source.current) return;
    setEffect(kind);
    const p = recipe(
      source.current.id,
      Math.min(source.current.duration, 30),
      kind,
    );
    p.alignment_us = project?.alignment_us ?? null;
    updateProject(p);
    clock.current = 0;
    void frameAt(0.08, p).catch(fail);
    setPlaying(false);
  }
  async function connect() {
    if (connecting) return null;
    setConnecting(true);
    setError("");
    const client = new DeviceClient(url, apiToken);
    try {
      const info = await client.connect();
      setNeedsToken(info.access_mode === "bearer");
      setDevice(client);
      setDialog(null);
      setMessage("Camera connected");
      await refreshRemote(client);
      return client;
    } catch (e) {
      if (e instanceof DeviceApiError && e.status === 401) {
        setNeedsToken(true);
        setDialog("device");
      }
      fail(e);
      return null;
    } finally {
      setConnecting(false);
    }
  }
  function openDeviceDialog() {
    setError("");
    setDialog("device");
  }
  async function refreshRemote(client = device) {
    if (client) setRemote((await client.request("/v1/recordings")).items);
  }
  async function startLive() {
    if (progress !== null) return;
    if (live.current) {
      await live.current.close();
      live.current = null;
      setLiveOn(false);
      if (source.current) {
        renderer.current?.setCalibration(source.current.calibration);
        setTitle(source.current.id);
        setSourceKind(
          source.current instanceof StillSource
            ? "360 still-frame reframing"
            : "Recorded dual fisheye",
        );
        await frameAt(clock.current);
      }
      setMessage("Live preview closed · camera recording is independent");
      return;
    }
    const camera = device ?? (await connect());
    if (!camera) return;
    setError("");
    setPlaying(false);
    setLoading(true);
    try {
      const c = await camera.request("/v1/calibration");
      if (!c.profile)
        throw new Error(
          "Add a valid calibration to enable VR preview. Raw recording is still available.",
        );
      if (!renderer.current)
        renderer.current = await Renderer.create(canvas.current!, c.profile);
      else renderer.current.setCalibration(c.profile);
      live.current = await camera.preview(video.current!, setDiagnostics);
      setLiveOn(true);
      setTitle("Live camera");
      setSourceKind("Paired fisheye stream");
      setMessage("Live preview · rendered on this device");
      setLoading(false);
    } catch (e) {
      fail(e);
    }
  }
  async function record() {
    if (!device) return;
    try {
      if (status?.recording) {
        await device.stopRecording();
        setMessage("Recording finalized");
        await refreshRemote();
      } else {
        await device.startCapture();
        const s = await device.request("/v1/status");
        if (!s.sync.locked) {
          setMessage(
            "Cameras are synchronizing. Start recording when the sync indicator is ready.",
          );
          return;
        }
        await device.startRecording();
        setMessage("Recording on camera · closing this tab will not stop it");
      }
      setStatus(await device.request("/v1/status"));
    } catch (e) {
      fail(e);
    }
  }
  async function exportCurrent() {
    if (!project || !source.current) return;
    setPlaying(false);
    setDialog(null);
    setProgress(0);
    setError("");
    abort.current = new AbortController();
    exporting.current = true;
    try {
      exportCleanup.current?.();
      setDownloadReady(null);
      const result = await exportVideo(
        source.current,
        project,
        spherical ? 1440 : size[0],
        spherical ? 720 : size[1],
        setProgress,
        abort.current.signal,
        spherical,
      );
      downloadBlob(result.file, `${project.source_id}-${effect}.mp4`);
      setMessage("Export complete · saved on this device");
      const name = `${project.source_id}-${effect}.mp4`;
      const url = URL.createObjectURL(result.file);
      setDownloadReady({ url, name });
      exportCleanup.current = () => {
        URL.revokeObjectURL(url);
        void result.cleanup().catch(() => {});
      };
    } catch (e) {
      fail(e);
    } finally {
      exporting.current = false;
      setProgress(null);
    }
  }
  const drag = useRef<{ x: number; y: number; a: number[] } | null>(null);
  return (
    <div className="app">
      <aside className="rail">
        <a className="brand" href="/" aria-label="RPI360 home">
          <Aperture size={28} />
        </a>
        <button
          className={tab === "library" ? "active" : ""}
          aria-label="Media library"
          onClick={() => setTab("library")}
        >
          <Layers />
        </button>
        <button
          className={tab === "effects" ? "active" : ""}
          aria-label="Effects"
          onClick={() => setTab("effects")}
        >
          <Clapperboard />
        </button>
        <button
          className={tab === "device" ? "active" : ""}
          aria-label="Camera"
          onClick={() => {
            setTab("device");
            void refreshRemote();
          }}
        >
          <Camera />
        </button>
        <span className="rail-spacer" />
        <a
          className="help"
          href="https://github.com/Henry-Chi-0221/rpi360"
          target="_blank"
          rel="noreferrer"
          aria-label="Documentation"
        >
          <CircleHelp size={20} />
        </a>
        <span className="version">v2 α</span>
      </aside>
      <aside className="library" inert={progress !== null}>
        <div className="wordmark">
          RPI<span>360</span>
          <small>WORKSPACE</small>
        </div>
        <div className="library-heading">
          <h2>
            {tab === "effects"
              ? "Creative tools"
              : tab === "device"
                ? "Camera & files"
                : "Your library"}
          </h2>
          <button
            className="icon"
            aria-label="Import media"
            onClick={() => fileInput.current?.click()}
          >
            <Plus size={17} />
          </button>
        </div>
        <input
          hidden
          ref={fileInput}
          type="file"
          multiple
          accept=".mp4,.zip,.json,.jsonl"
          onChange={(e) => void importFiles(Array.from(e.target.files ?? []))}
        />
        <input
          hidden
          ref={folderInput}
          type="file"
          multiple
          {...({ webkitdirectory: "" } as any)}
          onChange={(e) => void importFiles(Array.from(e.target.files ?? []))}
        />
        <input
          hidden
          ref={projectInput}
          type="file"
          accept=".json"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file)
              void file
                .text()
                .then((text) => {
                  const p: EditProject = JSON.parse(text);
                  evaluate(p, 0);
                  if (source.current?.id !== p.source_id)
                    throw new Error(
                      `Open source “${p.source_id}” first, then import this edit.`,
                    );
                  updateProject(p);
                  clock.current = 0;
                  return frameAt(0.08, p);
                })
                .catch(fail);
          }}
        />
        <button className="import" onClick={() => fileInput.current?.click()}>
          <FolderOpen size={17} />
          Import recording <Plus size={15} />
        </button>
        <button
          className="text-link"
          onClick={() => folderInput.current?.click()}
        >
          or choose a .r360 folder
        </button>
        <button
          className="text-link project-import"
          onClick={() => projectInput.current?.click()}
        >
          Open edit project
        </button>
        {tab === "library" && (
          <>
            <div className="section-label">
              EXPLORE A PERSPECTIVE <span>03</span>
            </div>
            <div className="demo-list">
              {catalog.map((d, i) => (
                <button
                  key={d.id}
                  className={`media-card ${active === d.id ? "selected" : ""}`}
                  disabled={loading || progress !== null}
                  onClick={() => void loadDemo(d).catch(fail)}
                >
                  <div
                    className="media-image"
                    style={{
                      backgroundImage: `url(/demo/${d.id}-poster.jpg),url(${d.image})`,
                    }}
                  >
                    <span className="image-kind">
                      <Globe2 size={12} />
                      360°
                    </span>
                    <span className="image-duration">STILL FRAME</span>
                  </div>
                  <div className="media-info">
                    <span>{d.title}</span>
                    <small>
                      {["Lakeside", "Architecture", "Waterfront"][i]}
                      <span>8 sec</span>
                    </small>
                  </div>
                </button>
              ))}
            </div>
            {localIds.length > 0 && (
              <>
                <div className="section-label">ON THIS DEVICE</div>
                {localIds.map((id) => (
                  <div className="local-row" key={id}>
                    <button
                      onClick={() =>
                        void localRecording(id)
                          .then((f) => RecordedSource.open(f))
                          .then((s) =>
                            attach(s, id.slice(0, 12), "Downloaded recording"),
                          )
                          .catch(fail)
                      }
                    >
                      {id.slice(0, 12)}
                    </button>
                    <button
                      aria-label="Delete downloaded copy"
                      onClick={() =>
                        void removeRecording(id)
                          .then(() => localRecordings())
                          .then(setLocalIds)
                      }
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </>
            )}
            {saved.length > 0 && (
              <>
                <div className="section-label">SAVED EDITS</div>
                {saved.map((p) => (
                  <button
                    className="saved-project"
                    key={p.id}
                    onClick={() => {
                      if (source.current?.id !== p.source_id) {
                        setMessage(
                          `Import source “${p.source_id}” before opening this edit.`,
                        );
                        return;
                      }
                      updateProject(p);
                      void frameAt(0, p).catch(fail);
                    }}
                  >
                    <Diamond size={13} />
                    {p.source_id}
                    <small>{p.keyframes.length} keyframes</small>
                  </button>
                ))}
              </>
            )}
          </>
        )}
        {tab === "effects" && (
          <>
            <div className="section-label">MAKE IT YOURS</div>
            <div className="effect-list">
              {presets.map(([id, name, description], i) => (
                <button
                  key={id}
                  className={effect === id ? "chosen" : ""}
                  onClick={() => applyPreset(id)}
                >
                  <span className={"effect-shape shape-" + i}>
                    <Globe2 size={25} />
                  </span>
                  <span>
                    {name}
                    <small>{description}</small>
                  </span>
                  <ArrowUpRight size={15} />
                </button>
              ))}
            </div>
            <p className="muted note">
              Each effect is an editable camera path. Adjust the keyframes to
              make it your own.
            </p>
          </>
        )}
        {tab === "device" && (
          <>
            <button className="connect-card" onClick={openDeviceDialog}>
              <Wifi size={21} />
              <span>
                {device ? "Camera connected" : "Connect your camera"}
                <small>Local network · SSH access</small>
              </span>
            </button>
            <button className="import" onClick={() => void startLive()}>
              <Video size={16} />
              {liveOn ? "Close live preview" : "Open live preview"}
            </button>
            <button
              className="import"
              disabled={!device}
              onClick={() => void record()}
            >
              <span
                className={
                  status?.recording ? "record-dot recording" : "record-dot"
                }
              />
              {status?.recording ? "Stop recording" : "Start recording"}
            </button>
            <div className="section-label">
              ON CAMERA{" "}
              <button
                className="text-link"
                onClick={() => void refreshRemote()}
              >
                Refresh
              </button>
            </div>
            {remote.map((r) => (
              <div className="remote-file" key={r.id}>
                <span>
                  {r.id.slice(0, 12)}
                  <small>
                    {r.state} ·{" "}
                    {Math.round(r.files.reduce((n, f) => n + f.bytes, 0) / 1e6)}{" "}
                    MB
                  </small>
                </span>
                <button
                  disabled={
                    !["complete", "recovered"].includes(r.state) ||
                    progress !== null
                  }
                  aria-label="Download recording"
                  onClick={() => {
                    abort.current = new AbortController();
                    setProgress(0);
                    void downloadRecording(
                      device!,
                      r,
                      setProgress,
                      abort.current.signal,
                    )
                      .then(async (f) => {
                        setLocalIds(await localRecordings());
                        await attach(
                          await RecordedSource.open(f),
                          r.id.slice(0, 12),
                          "Downloaded recording",
                        );
                      })
                      .catch(fail)
                      .finally(() => setProgress(null));
                  }}
                >
                  <ArrowDownToLine size={16} />
                </button>
              </div>
            ))}
          </>
        )}
        <div className="local-first">
          <span className="status-dot" />
          <div>
            Made on your device<small>Your footage stays with you.</small>
          </div>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <span>/</span> <strong>Reframe</strong>
          </div>
          <div className="header-actions">
            <button
              className={"device-status " + (device ? "connected" : "")}
              onClick={openDeviceDialog}
            >
              <span className="status-dot" />
              {device ? "Camera connected" : "Connect camera"}
            </button>
            <button
              className="primary"
              disabled={!project || liveOn || progress !== null}
              onClick={() => setDialog("export")}
            >
              <ArrowUpRight size={16} />
              Export video
            </button>
          </div>
        </header>
        <div className="editor-header">
          <div>
            <div className="eyebrow">A NEW WAY TO SEE</div>
            <h1>{title}</h1>
            <p>
              {sourceKind} <span>•</span>{" "}
              {liveOn
                ? "Live"
                : `${project ? (project.duration_us / 1e6).toFixed(1) : 8} seconds`}{" "}
              <span>•</span> Dual fisheye
            </p>
          </div>
          <button
            className="subtle"
            onClick={() => {
              if (project)
                void saveProject(project)
                  .then(() => projects())
                  .then((p) => {
                    setSaved(p);
                    setMessage("Project saved on this device");
                  })
                  .catch(fail);
            }}
            disabled={!project}
          >
            <Save size={15} />
            Save edit
          </button>
        </div>
        <div className="work-area">
          <section className="viewer-area">
            <div className="viewer-toolbar">
              <div className="segmented">
                {[
                  ["view", "Reframe"],
                  ["panorama", "Panorama"],
                  ["raw", "Source"],
                ].map(([id, label]) => (
                  <button
                    key={id}
                    className={mode === id ? "selected" : ""}
                    onClick={() => setMode(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <button
                className="aspect"
                onClick={() =>
                  canvas.current?.parentElement?.requestFullscreen()
                }
              >
                <Maximize2 size={15} />
              </button>
            </div>
            <div
              className="viewport"
              onPointerDown={(e) => {
                if (mode !== "raw") {
                  e.currentTarget.setPointerCapture(e.pointerId);
                  drag.current = { x: e.clientX, y: e.clientY, a: angles };
                }
              }}
              onPointerMove={(e) => {
                if (drag.current) {
                  const d = drag.current;
                  manual([
                    d.a[0] - (e.clientX - d.x) * 0.15,
                    Math.max(
                      -90,
                      Math.min(90, d.a[1] + (e.clientY - d.y) * 0.15),
                    ),
                    d.a[2],
                  ]);
                }
              }}
              onPointerUp={() => {
                drag.current = null;
              }}
              onPointerCancel={() => {
                drag.current = null;
              }}
              onLostPointerCapture={() => {
                drag.current = null;
              }}
              onWheel={(e) =>
                manual(
                  angles,
                  Math.max(
                    25,
                    Math.min(
                      view.projection === "perspective" ? 170 : 340,
                      view.horizontal_fov_deg + e.deltaY * 0.04,
                    ),
                  ),
                )
              }
            >
              <canvas
                ref={canvas}
                className={mode === "raw" ? "hidden" : ""}
                width="1280"
                height="720"
                style={{
                  aspectRatio:
                    mode === "panorama" ? "2/1" : ratio.replace(":", "/"),
                }}
                aria-label="Interactive 360 preview"
              />
              <canvas
                ref={rawCanvas}
                className={mode === "raw" ? "" : "hidden"}
                aria-label="Unstitched paired fisheye source"
              />
              {loading && (
                <div className="loading">
                  <LoaderCircle className="spin" />
                  Preparing your perspective…
                </div>
              )}
            </div>
            <div className="viewer-caption">
              <span>
                <Globe2 size={14} />
                Drag to look around <span className="separator">·</span> Scroll
                to zoom
              </span>
              <span>
                {liveOn ? (
                  <>
                    <span className="live-indicator" />
                    LIVE · {status?.sync?.locked ? "Synced" : "Synchronizing"}
                  </>
                ) : sourceKind === "360 still-frame reframing" ? (
                  "360 still-frame demo"
                ) : (
                  "Original source timing"
                )}
              </span>
            </div>
            <Timeline
              project={project}
              time={time}
              playing={playing}
              disabled={liveOn || progress !== null || loading}
              poster={
                catalog.some((d) => d.id === active)
                  ? `/demo/${active}-poster.jpg`
                  : undefined
              }
              onPlay={() => {
                if (
                  !playing &&
                  clock.current >= (project?.duration_us ?? 0) / 1e6
                )
                  clock.current = 0;
                setPlaying(!playing);
              }}
              onSeek={(t) => {
                clock.current = t;
                setPlaying(false);
                void frameAt(t).catch(fail);
              }}
              onAdd={addKeyframe}
              onDelete={(t) => {
                if (project && t !== 0)
                  updateProject({
                    ...project,
                    keyframes: project.keyframes.filter((k) => k.time_us !== t),
                  });
              }}
            />
          </section>
          <Inspector
            view={view}
            angles={angles}
            ratio={ratio}
            effect={effect}
            alignment={alignment}
            unknownAlignment={
              !liveOn &&
              !!source.current &&
              !source.current.alignmentKnown &&
              sourceKind !== "360 still-frame reframing"
            }
            onManual={manual}
            onRatio={setRatio}
            onEffect={applyPreset}
            onEffects={() => setTab("effects")}
            onAlignment={(value) => {
              setAlignment(value);
              if (project)
                updateProject({
                  ...project,
                  alignment_us: Math.round(+value * 1000),
                });
            }}
          />
        </div>
        <footer>
          {downloadReady && (
            <a href={downloadReady.url} download={downloadReady.name}>
              Download export
            </a>
          )}
          <span className={error ? "error-text" : ""}>{error || message}</span>
          {progress !== null ? (
            <span className="progress">
              <progress value={progress} max="1" />
              {Math.round(progress * 100)}%
              <button
                className="text-link"
                onClick={() => abort.current?.abort()}
              >
                Cancel
              </button>
            </span>
          ) : (
            <span>
              {liveOn && diagnostics
                ? `Pair Δ ${Math.round(diagnostics.delta_us)} μs`
                : "Local processing"}
              <span className="footer-dot" />
              RPI360 α
            </span>
          )}
        </footer>
      </main>
      <video hidden ref={video} autoPlay playsInline muted />
      {dialog && (
        <div className="modal-backdrop" onClick={() => setDialog(null)}>
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label={dialog === "device" ? "Connect camera" : "Export video"}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close icon"
              aria-label="Close dialog"
              onClick={() => setDialog(null)}
            >
              <X size={20} />
            </button>
            {dialog === "device" ? (
              <>
                <Wifi className="modal-symbol" />
                <h2>Connect your camera</h2>
                <p>
                  Connect through SSH and open your live camera. No pairing code
                  or browser account is needed.
                </p>
                <label>
                  Device address
                  <input
                    value={url}
                    onChange={(e) => {
                      setUrl(e.target.value);
                      setNeedsToken(false);
                      setApiToken("");
                    }}
                    placeholder="/api"
                  />
                </label>
                {needsToken && (
                  <label>
                    API token for this HTTPS deployment
                    <input
                      type="password"
                      value={apiToken}
                      onChange={(e) => setApiToken(e.target.value)}
                      autoComplete="off"
                    />
                  </label>
                )}
                <p className="hint">
                  For the default workflow, run{" "}
                  <code>make preview CAMERA=user@raspberrypi.local</code> from
                  your checkout. Keep the default device address. On macOS, the
                  services keep running after the terminal closes.
                </p>
                <p className="hint">
                  <a
                    href="https://github.com/Henry-Chi-0221/rpi360/blob/codex/rpi360-v2/docs/getting-started/camera.md"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Camera setup guide
                  </a>
                </p>
                <button
                  className="primary full"
                  disabled={connecting}
                  onClick={() => void connect()}
                >
                  <Link2 size={16} />
                  {connecting ? "Connecting…" : "Connect camera"}
                </button>
              </>
            ) : (
              <>
                <ArrowUpRight className="modal-symbol" />
                <h2>Ready for a new perspective?</h2>
                <p>
                  Export your edit as an H.264 MP4, directly on this device.
                </p>
                <label className="export-mode">
                  Export format
                  <select
                    value={spherical ? "360" : "flat"}
                    onChange={(e) => setSpherical(e.target.value === "360")}
                  >
                    <option value="flat">Reframed MP4</option>
                    <option value="360">360° equirectangular MP4 · 2:1</option>
                  </select>
                </label>
                <div className="export-summary">
                  <span>
                    Resolution
                    <strong>
                      {spherical ? 1440 : size[0]} × {spherical ? 720 : size[1]}
                    </strong>
                  </span>
                  <span>
                    Output frame rate<strong>30 fps</strong>
                  </span>
                  <span>
                    Duration
                    <strong>
                      {timecode((project?.duration_us ?? 0) / 1e6)}
                    </strong>
                  </span>
                </div>
                <p className="hint">
                  Virtual camera motion is rendered at 30 fps. Original footage
                  keeps its captured motion; no artificial frames are generated.
                </p>
                <button
                  className="primary full"
                  onClick={() => void exportCurrent()}
                >
                  <ArrowDownToLine size={16} />
                  Export video
                </button>
                <button
                  className="subtle full"
                  onClick={() => {
                    if (project)
                      downloadBlob(
                        new Blob([JSON.stringify(project, null, 2)], {
                          type: "application/json",
                        }),
                        "edit.r360-project.json",
                      );
                  }}
                >
                  Download edit project
                </button>
              </>
            )}
            {error && <p className="error-text">{error}</p>}
          </section>
        </div>
      )}
    </div>
  );
}
