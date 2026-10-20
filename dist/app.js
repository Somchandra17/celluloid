import { canvasTheme, setWorld } from "./theme.js";
import {
  makePalette,
  quantize,
  createDemo,
  columnName,
  validateClip,
  serializeClip,
  transformClip,
  LIMITS,
} from "./core.js";
import { createOds, ODS_LIMITS } from "./ods.js";

const $ = (id) => document.getElementById(id);
const state = {
  clip: createDemo(),
  frame: 0,
  playing: !matchMedia("(prefers-reduced-motion: reduce)").matches,
  loop: true,
  mode: "file",
  palette: "color",
  file: null,
  sourceKind: "demo",
  originalClip: null,
  url: null,
  stream: null,
  record: null,
  busy: false,
  job: 0,
  abort: null,
  lastTick: 0,
  toastTimer: null,
  bridge: null,
};
const video = $("source-video"),
  canvas = $("sheet-canvas"),
  ctx = canvas.getContext("2d"),
  sampleCanvas = document.createElement("canvas"),
  sampleCtx = sampleCanvas.getContext("2d", { willReadFrequently: true });
const icon = (name) => `<svg><use href="#i-${name}"/></svg>`;
const formatTime = (seconds) =>
  `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
function toast(message, error = false) {
  clearTimeout(state.toastTimer);
  $("toast").textContent = message;
  $("toast").classList.toggle("error", error);
  $("toast").hidden = false;
  state.toastTimer = setTimeout(
    () => ($("toast").hidden = true),
    error ? 9000 : 6500,
  );
}
function activeSettings() {
  return {
    width: Number($("resolution").value),
    fps: Number($("fps").value),
    mode: state.palette,
    duration: Number($("duration").value),
    start: Math.max(0, Number($("start-offset").value) || 0),
  };
}
function setBusy(busy, label = "Converting video…") {
  state.busy = busy;
  $("canvas-overlay").hidden = !busy;
  $("cancel-convert").disabled = false;
  $("progress-label").textContent = label;
  for (const id of [
    "convert-button",
    "file-input",
    "export-button",
    "json-button",
    "start-camera",
    "record-button",
    "sample-button",
    "resolution",
    "fps",
    "duration",
    "start-offset",
    "backend-url",
    "file-tab",
    "camera-tab",
    "play-button",
    "restart-button",
    "step-button",
    "timeline",
  ])
    $(id).disabled = busy;
  document
    .querySelectorAll(".palette-option")
    .forEach((b) => (b.disabled = busy));
  if (!busy) $("record-button").disabled = !state.stream;
}
function playbackButton() {
  $("play-button").innerHTML = icon(state.playing ? "pause" : "play");
  $("play-button").setAttribute("aria-label", state.playing ? "Pause" : "Play");
  $("render-status").textContent = state.stream
    ? "Live camera"
    : state.playing
      ? state.sourceKind === "demo"
        ? "Playing sample"
        : "Playing clip"
      : "Paused";
}
function configureClip(clip, title) {
  state.clip = validateClip(clip);
  state.clip.frames = state.clip.frames.map((f) =>
    f instanceof Uint8Array ? f : new Uint8Array(f),
  );
  state.clip.title = title || clip.title || "My cell animation";
  state.frame = 0;
  state.lastTick = 0;
  $("document-name").textContent =
    state.clip.title.replace(/\.[^.]+$/, "") + ".cells";
  $("timeline").max = clip.frames.length - 1;
  $("timeline").value = 0;
  $("total-time").textContent = formatTime(clip.frames.length / clip.fps);
  $("stats-size").textContent = `${clip.width} × ${clip.height}`;
  $("stats-fps").textContent = `${clip.fps} fps`;
  $("stats-frames").textContent = `${clip.frames.length} frames`;
  $("cell-range").textContent =
    `A1:${columnName(clip.width - 1)}${clip.height}`;
  $("cell-count-label").textContent =
    `${(clip.width * clip.height).toLocaleString()} cells`;
  $("footer-metric").textContent =
    `${(clip.width * clip.height).toLocaleString()} cells. Endless possibilities.`;
  playbackButton();
  draw();
  sendNative();
}
function draw() {
  const { clip, frame } = state,
    pixels = clip.frames[frame];
  if (!pixels) return;
  const rect = canvas.getBoundingClientRect(),
    dpr = Math.min(devicePixelRatio || 1, 2),
    W = rect.width,
    H = rect.height;
  if (!W || !H) return;
  if (
    canvas.width !== Math.round(W * dpr) ||
    canvas.height !== Math.round(H * dpr)
  ) {
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
  }
  const theme = canvasTheme();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = theme.ground;
  ctx.fillRect(0, 0, W, H);
  const left = 29,
    top = 22,
    cell = Math.min((W - left) / clip.width, (H - top) / clip.height),
    gw = cell * clip.width,
    gh = cell * clip.height;
  ctx.fillStyle = theme.ground;
  ctx.fillRect(left, top, W - left, H - top);
  for (let y = 0; y < clip.height; y++)
    for (let x = 0; x < clip.width; x++) {
      ctx.fillStyle = clip.palette[pixels[y * clip.width + x]];
      ctx.fillRect(left + x * cell, top + y * cell, cell + 0.15, cell + 0.15);
    }
  if ($("grid-toggle").checked) {
    ctx.beginPath();
    ctx.strokeStyle = theme.grid;
    ctx.lineWidth = 0.5;
    for (let x = 0; x <= clip.width; x++) {
      ctx.moveTo(left + x * cell, top);
      ctx.lineTo(left + x * cell, top + gh);
    }
    for (let y = 0; y <= clip.height; y++) {
      ctx.moveTo(left, top + y * cell);
      ctx.lineTo(left + gw, top + y * cell);
    }
    ctx.stroke();
  }
  ctx.fillStyle = theme.chrome;
  ctx.fillRect(0, 0, W, top);
  ctx.fillRect(0, top, left, H - top);
  ctx.strokeStyle = theme.rule;
  ctx.lineWidth = 0.5;
  ctx.beginPath();
  ctx.moveTo(0, top - 0.5);
  ctx.lineTo(W, top - 0.5);
  ctx.moveTo(left - 0.5, 0);
  ctx.lineTo(left - 0.5, H);
  ctx.stroke();
  ctx.font = "8px monospace";
  ctx.fillStyle = theme.label;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const colSkip = Math.max(1, Math.ceil(25 / cell)),
    rowSkip = Math.max(1, Math.ceil(15 / cell));
  for (let x = 0; x < clip.width; x += colSkip)
    ctx.fillText(columnName(x), left + (x + 0.5) * cell, top / 2);
  for (let y = 0; y < clip.height; y += rowSkip)
    ctx.fillText(String(y + 1), left / 2, top + (y + 0.5) * cell);
  ctx.fillStyle = theme.corner;
  ctx.beginPath();
  ctx.moveTo(18, 6);
  ctx.lineTo(18, 15);
  ctx.lineTo(9, 15);
  ctx.fill();
  $("timeline").value = frame;
  $("current-time").textContent = formatTime(frame / clip.fps);
  $("formula-text").textContent = state.stream
    ? "live light, translated into cells"
    : `frame ${String(frame + 1).padStart(3, "0")} / ${String(clip.frames.length).padStart(3, "0")}  ·  a different kind of motion picture`;
}
function showMode(mode) {
  if (state.busy) return;
  if (mode === "file" && state.stream) stopCamera();
  state.mode = mode;
  for (const name of ["file", "camera"]) {
    $(`${name}-source`).hidden = mode !== name;
    $(`${name}-tab`).classList.toggle("active", mode === name);
    $(`${name}-tab`).setAttribute("aria-selected", String(mode === name));
    $(`${name}-tab`).tabIndex = mode === name ? 0 : -1;
  }
}
function stopCamera() {
  const wasCamera = !!state.stream;
  if (state.record) finishRecording();
  if (state.stream) {
    state.stream.getTracks().forEach((t) => t.stop());
    state.stream = null;
  }
  state.live = null;
  video.srcObject = null;
  video.pause();
  $("live-label").hidden = true;
  $("start-camera").hidden = false;
  $("stop-camera").hidden = true;
  $("record-button").disabled = true;
  document.body.classList.remove("camera-active");
  cameraStatus("Camera is off. Click Enable camera to request access.");
  $("stats-frames").textContent = `${state.clip.frames.length} frames`;
  if (wasCamera) configureClip(state.clip);
  playbackButton();
}
function readFrame(width, height, mode, mirror = false) {
  sampleCanvas.width = width;
  sampleCanvas.height = height;
  sampleCtx.save();
  if (mirror) {
    sampleCtx.translate(width, 0);
    sampleCtx.scale(-1, 1);
  }
  sampleCtx.drawImage(video, 0, 0, width, height);
  sampleCtx.restore();
  return quantize(sampleCtx.getImageData(0, 0, width, height).data, mode);
}
function dimensions(width, sourceWidth, sourceHeight) {
  const ratio = sourceWidth / sourceHeight;
  let height = Math.max(1, Math.round(width / ratio));
  if (height > 90) {
    height = 90;
    width = Math.max(1, Math.round(height * ratio));
  }
  return { width, height };
}
function mediaEvent(name, timeout = 18000) {
  return new Promise((resolve, reject) => {
    const signal = state.abort?.signal;
    let timer;
    const cleanup = () => {
      clearTimeout(timer);
      video.removeEventListener(name, success);
      video.removeEventListener("error", error);
      signal?.removeEventListener("abort", abort);
    };
    const success = (e) => {
        cleanup();
        resolve(e);
      },
      error = () => {
        cleanup();
        reject(
          Error(
            "This video could not be decoded. Try an MP4/WebM file or configure the FFmpeg backend.",
          ),
        );
      },
      abort = () => {
        cleanup();
        reject(new DOMException("Cancelled", "AbortError"));
      };
    if (signal?.aborted) {
      abort();
      return;
    }
    video.addEventListener(name, success, { once: true });
    video.addEventListener("error", error, { once: true });
    signal?.addEventListener("abort", abort, { once: true });
    timer = setTimeout(() => {
      cleanup();
      reject(
        Error(
          "Video decoding timed out. Try a shorter clip or use the FFmpeg backend.",
        ),
      );
    }, timeout);
  });
}
async function loadMedia(file) {
  video.pause();
  video.removeAttribute("src");
  video.srcObject = null;
  video.preload = "auto";
  if (state.url) URL.revokeObjectURL(state.url);
  state.url = URL.createObjectURL(file);
  const loaded = mediaEvent("loadedmetadata");
  video.src = state.url;
  video.load();
  await loaded;
  if (
    !Number.isFinite(video.duration) ||
    video.duration <= 0 ||
    !video.videoWidth
  )
    throw Error(
      "The selected file does not contain a finite, decodable video.",
    );
  // Metadata does not imply a decoded frame. Seeking to the initial position
  // can be a no-op, so wait for pixels before sampling or seeking from zero.
  if (video.readyState < 2) await mediaEvent("loadeddata");
}
async function seek(time) {
  const t = Math.min(Math.max(0, time), Math.max(0, video.duration - 0.001));
  if (Math.abs(video.currentTime - t) < 0.00001 && video.readyState >= 2)
    return;
  const waiting = mediaEvent("seeked");
  video.currentTime = t;
  await waiting;
}
async function convertFile(file) {
  if (state.busy) return;
  stopCamera();
  showMode("file");
  state.playing = false;
  playbackButton();
  setBusy(true);
  $("progress").value = 0;
  const job = ++state.job,
    settings = activeSettings();
  state.abort = new AbortController();
  try {
    let clip;
    const backend = $("backend-url").value.trim();
    if (file.name.toLowerCase().endsWith(".json")) {
      if (file.size > 25 * 1024 * 1024)
        throw Error("Frame-data files must be under 25 MB.");
      clip = validateClip(JSON.parse(await file.text()));
    } else if (backend) {
      const endpoint = new URL(backend);
      if (!["http:", "https:"].includes(endpoint.protocol))
        throw Error("Use an HTTP or HTTPS backend address.");
      const form = new FormData();
      form.append("file", file);
      for (const [key, value] of Object.entries({
        width: settings.width,
        fps: settings.fps,
        duration: settings.duration,
        start: settings.start,
        palette: settings.mode,
      }))
        form.append(key, String(value));
      $("progress-label").textContent = "Converting with your FFmpeg backend…";
      const response = await fetch(
        endpoint.href.replace(/\/$/, "") + "/api/convert",
        { method: "POST", body: form, signal: state.abort.signal },
      );
      if (!response.ok) {
        let message;
        try {
          message = (await response.json()).detail;
        } catch {}
        throw Error(
          typeof message === "string"
            ? message
            : `Backend returned ${response.status}. Check its CORS origin and logs.`,
        );
      }
      clip = validateClip(await response.json());
    } else {
      await loadMedia(file);
      if (settings.start >= video.duration)
        throw Error("Start time is beyond the end of the video.");
      const { width, height } = dimensions(
          settings.width,
          video.videoWidth,
          video.videoHeight,
        ),
        duration = Math.min(
          settings.duration,
          video.duration - settings.start,
          LIMITS.frames / settings.fps,
        ),
        count = Math.max(1, Math.ceil(duration * settings.fps)),
        frames = [];
      for (let i = 0; i < count; i++) {
        if (job !== state.job)
          throw new DOMException("Cancelled", "AbortError");
        await seek(settings.start + i / settings.fps);
        frames.push(readFrame(width, height, settings.mode));
        $("progress").value = ((i + 1) / count) * 100;
        $("progress-label").textContent =
          `Turning frame ${i + 1} of ${count} into cells…`;
        if (i % 5 === 0) await new Promise((r) => setTimeout(r, 0));
      }
      clip = {
        version: 1,
        width,
        height,
        fps: settings.fps,
        palette: makePalette(settings.mode),
        frames,
        duration: frames.length / settings.fps,
      };
    }
    if (job !== state.job) throw new DOMException("Cancelled", "AbortError");
    state.file = file;
    state.sourceKind = file.name.toLowerCase().endsWith(".json")
      ? "data"
      : "upload";
    state.originalClip = clip;
    state.playing = true;
    $("source-name").textContent = file.name;
    $("source-detail").textContent =
      `${(file.size / 1024 / 1024).toFixed(1)} MB · ${clip.frames.length} frames converted`;
    configureClip(clip, file.name);
    toast(
      `Ready. ${clip.frames.length} frames, ${(clip.width * clip.height).toLocaleString()} real cell colors per frame.`,
    );
  } catch (e) {
    if (e.name === "AbortError") toast("Conversion request cancelled.");
    else toast(e.message || "Conversion failed.", true);
  } finally {
    setBusy(false);
    state.abort = null;
    playbackButton();
  }
}
async function acceptFile(file) {
  if (!file || state.busy) return;
  if (file.size > LIMITS.file) {
    toast("Choose a file smaller than 100 MB.", true);
    return;
  }
  if (
    !(
      file.type.startsWith("video/") ||
      /\.(mp4|webm|mov|mkv|avi|m4v|ogv|json)$/i.test(file.name)
    )
  ) {
    toast("Choose a video file or exported Celluloid JSON.", true);
    return;
  }
  await convertFile(file);
}
function cameraStatus(message, error = false) {
  $("camera-status").textContent = message;
  $("camera-status").classList.toggle("camera-error", error);
  if (error) $("camera-help").open = true;
}
async function startCamera() {
  if (state.busy) return;
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    const message =
      "Camera access needs HTTPS or localhost. Open the companion's http://127.0.0.1 local URL directly in a browser tab.";
    cameraStatus(message, true);
    toast(message, true);
    return;
  }
  const policy = document.permissionsPolicy || document.featurePolicy;
  if (policy?.allowsFeature && !policy.allowsFeature("camera")) {
    const message =
      "This page's permissions policy blocks the camera. Open Celluloid in its own tab at the companion's local URL.";
    cameraStatus(message, true);
    toast(message, true);
    return;
  }
  if (state.stream) return;
  state.playing = false;
  playbackButton();
  $("start-camera").disabled = true;
  $("start-camera").textContent = "Requesting camera…";
  cameraStatus(
    "Requesting camera access… Check the permission indicator near Arc/Chromium's address bar. If no prompt appears, open the help below.",
  );
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 640 },
        height: { ideal: 360 },
        facingMode: "user",
      },
      audio: false,
    });
    if (state.mode !== "camera") {
      stream.getTracks().forEach((t) => t.stop());
      cameraStatus(
        "Camera request ended because the source changed. Select Webcam and try again.",
      );
      return;
    }
    state.stream = stream;
    video.removeAttribute("src");
    video.srcObject = stream;
    await video.play();
    stream.getVideoTracks()[0].addEventListener("ended", () => {
      stopCamera();
      cameraStatus("Camera disconnected. Click Enable camera to reconnect.");
      toast("Camera disconnected.");
    });
    $("start-camera").hidden = true;
    $("stop-camera").hidden = false;
    $("record-button").disabled = false;
    $("live-label").hidden = false;
    document.body.classList.add("camera-active");
    state.lastTick = 0;
    cameraStatus("Camera is live. Frames stay on this device.");
    toast("Camera is live. Each frame is converted locally into cell colors.");
  } catch (e) {
    stopCamera();
    const message =
      e.name === "NotAllowedError" || e.name === "SecurityError"
        ? "Camera permission was denied or blocked. Allow this local site in Arc/Chromium's camera settings. On macOS, also allow your browser in System Settings → Privacy & Security → Camera, then reopen it."
        : e.name === "NotFoundError"
          ? "No camera was found on this device."
          : e.name === "NotReadableError" || e.name === "TrackStartError"
            ? "The camera is busy or unavailable. Close other camera apps and check your browser's macOS Camera permission, then try again."
            : `Could not start camera: ${e.message}`;
    cameraStatus(message, true);
    toast(message, true);
  } finally {
    $("start-camera").disabled = state.busy;
    $("start-camera").textContent = "Enable camera";
  }
}
function startRecording() {
  if (!state.stream) return;
  if (state.record) {
    finishRecording();
    return;
  }
  const settings = activeSettings();
  state.record = {
    frames: [],
    ...dimensions(settings.width, video.videoWidth, video.videoHeight),
    fps: settings.fps,
    palette: makePalette(settings.mode),
    mode: settings.mode,
    target: Math.min(10 * settings.fps, LIMITS.frames),
  };
  $("record-button").classList.add("recording");
  $("record-button").innerHTML =
    '<span class="record-dot"></span> Stop recording';
  $("record-status").textContent = "Recording cell frames…";
}
function finishRecording() {
  const record = state.record;
  state.record = null;
  $("record-button").classList.remove("recording");
  $("record-button").innerHTML =
    '<span class="record-dot"></span> Record a 10-second clip';
  if (record?.frames.length) {
    configureClip(
      {
        version: 1,
        width: record.width,
        height: record.height,
        fps: record.fps,
        palette: record.palette,
        frames: record.frames,
        duration: record.frames.length / record.fps,
      },
      "Webcam recording",
    );
    state.file = null;
    state.sourceKind = "recording";
    state.originalClip = state.clip;
    $("source-name").textContent = "Webcam recording";
    $("source-detail").textContent = `${record.frames.length} frames captured`;
    $("record-status").textContent =
      `Captured ${record.frames.length} frames. Turn off the camera to review or export.`;
    toast(
      "Recording saved in this tab. Turn off the camera to review or export.",
    );
  } else
    $("record-status").textContent = "No frames captured. Try recording again.";
}
function cameraFrame() {
  if (!video.videoWidth || video.readyState < 2) return;
  const settings = activeSettings(),
    record = state.record,
    dims =
      record || dimensions(settings.width, video.videoWidth, video.videoHeight),
    mode = record?.mode || settings.mode,
    pixels = readFrame(dims.width, dims.height, mode, $("mirror").checked),
    palette = record?.palette || makePalette(mode);
  if (record) {
    record.frames.push(pixels);
    $("record-status").textContent =
      `Recording ${(record.frames.length / record.fps).toFixed(1)} / 10 seconds · ${record.frames.length} frames`;
  }
  // Keep the recorded clip separate from the one-frame live display.
  state.live = {
    version: 1,
    width: dims.width,
    height: dims.height,
    fps: record?.fps || settings.fps,
    palette,
    frames: [pixels],
  };
  const saved = state.clip,
    savedFrame = state.frame;
  state.clip = state.live;
  state.frame = 0;
  draw();
  state.clip = saved;
  state.frame = savedFrame;
  $("stats-size").textContent = `${dims.width} × ${dims.height}`;
  $("stats-fps").textContent = `${settings.fps} fps`;
  $("stats-frames").textContent = "Live feed";
  $("cell-range").textContent =
    `A1:${columnName(dims.width - 1)}${dims.height}`;
  sendNative(state.live, pixels);
  if (record && record.frames.length >= record.target) finishRecording();
}
function tick(time) {
  requestAnimationFrame(tick);
  if (state.busy) return;
  const fps = state.stream
    ? state.record?.fps || Number($("fps").value)
    : state.clip.fps;
  if (time - state.lastTick < 1000 / fps) return;
  const delta = state.lastTick
    ? Math.max(1, Math.floor((time - state.lastTick) / (1000 / fps)))
    : 1;
  state.lastTick = state.lastTick
    ? state.lastTick + delta * (1000 / fps)
    : time;
  if (state.stream) {
    cameraFrame();
    return;
  }
  if (!state.playing) return;
  const next = state.frame + delta;
  if (next >= state.clip.frames.length) {
    if (state.loop) state.frame = next % state.clip.frames.length;
    else {
      state.frame = state.clip.frames.length - 1;
      state.playing = false;
      playbackButton();
    }
  } else state.frame = next;
  draw();
  sendNative();
}
function download(blob, name) {
  const url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
function safeName() {
  return (
    (state.clip.title || "celluloid")
      .replace(/\.[^.]+$/, "")
      .replace(/[^a-zA-Z0-9_-]+/g, "-")
      .slice(0, 64) || "celluloid"
  );
}
function exportableClip() {
  if (state.stream)
    throw Error(
      "Turn off the camera before exporting. Record a clip first to export your live footage.",
    );
  if (state.busy) throw Error("Wait for conversion to finish.");
  return state.clip;
}
async function exportOds() {
  try {
    const clip = exportableClip();
    $("export-button").disabled = true;
    let output = clip;
    if (
      clip.width > ODS_LIMITS.maxWidth ||
      clip.height > ODS_LIMITS.maxHeight
    ) {
      const scale = Math.min(
          ODS_LIMITS.maxWidth / clip.width,
          ODS_LIMITS.maxHeight / clip.height,
        ),
        width = Math.max(1, Math.floor(clip.width * scale)),
        height = Math.max(1, Math.floor(clip.height * scale));
      output = {
        ...clip,
        width,
        height,
        frames: clip.frames.map((frame) =>
          Uint8Array.from(
            { length: width * height },
            (_, i) =>
              frame[
                Math.min(
                  clip.height - 1,
                  Math.floor((Math.floor(i / width) * clip.height) / height),
                ) *
                  clip.width +
                  Math.min(
                    clip.width - 1,
                    Math.floor(((i % width) * clip.width) / width),
                  )
              ],
          ),
        ),
      };
      toast(
        `ODS export resized to ${width} × ${height} to keep Calc playback manageable.`,
      );
    }
    await new Promise((r) => setTimeout(r, 30));
    download(createOds(output), safeName() + ".ods");
    $("help-dialog").showModal();
  } catch (e) {
    toast(e.message, true);
  } finally {
    $("export-button").disabled = state.busy;
  }
}
async function bridgeFetch(path, options = {}, connection = state.bridge) {
  const response = await fetch(connection.url + path, {
    ...options,
    headers: {
      Authorization: `Bearer ${connection.token}`,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
    signal: AbortSignal.timeout(12000),
  });
  if (!response.ok) {
    let message;
    try {
      message = (await response.json()).error;
    } catch {}
    throw Error(message || `Companion returned ${response.status}.`);
  }
  return response.json();
}
async function connectBridge() {
  const url = $("bridge-url").value.trim().replace(/\/$/, ""),
    token = $("bridge-token").value.trim();
  try {
    const parsed = new URL(url);
    if (!["127.0.0.1", "localhost", "[::1]"].includes(parsed.hostname))
      throw Error(
        "The Calc companion must run on your local machine (localhost or 127.0.0.1).",
      );
    if (!token)
      throw Error("Paste the pairing token printed by your companion.");
    $("connect-button").disabled = true;
    const candidate = {
      url,
      token,
      session: null,
      key: null,
      sequence: 0,
      busy: false,
    };
    const health = await bridgeFetch("/health", {}, candidate);
    if (health.protocol !== "cell-video-v1")
      throw Error("This is not a compatible Celluloid companion.");
    await disconnectBridge(false);
    state.bridge = candidate;
    candidate.mode = health.mode;
    $("bridge-token").value = "";
    $("bridge-status").textContent =
      health.mode === "simulation"
        ? "Connected to simulation. No real Calc cells are being changed."
        : "Connected. Frames will now update real LibreOffice Calc cells.";
    $("disconnect-button").disabled = false;
    document.querySelector(".connection-dot").classList.add("connected");
    sendNative();
    toast(
      health.mode === "simulation"
        ? "Simulation connected. Native Calc rendering is disabled."
        : "LibreOffice connected. Start playback to animate real cells.",
    );
  } catch (e) {
    $("bridge-status").textContent = e.message;
    toast(
      `${e.message} If the hosted page cannot reach localhost, open the companion's local web URL.`,
      true,
    );
  } finally {
    $("connect-button").disabled = false;
  }
}
async function disconnectBridge(show = true) {
  const bridge = state.bridge;
  state.bridge = null;
  document.querySelector(".connection-dot").classList.remove("connected");
  $("disconnect-button").disabled = true;
  if (bridge?.session) {
    try {
      await bridgeFetch(
        "/session",
        {
          method: "DELETE",
          body: JSON.stringify({ sessionId: bridge.session }),
        },
        bridge,
      );
    } catch {}
  }
  if (show) {
    $("bridge-status").textContent =
      "Disconnected. The last Calc frame stays visible.";
    toast("Calc disconnected.");
  }
}
async function sendNative(
  clip = state.clip,
  pixels = clip.frames[state.frame],
) {
  const b = state.bridge;
  if (!b || !pixels) return;
  if (b.busy) {
    b.pending = { clip, pixels };
    return;
  }
  b.busy = true;
  try {
    const key = `${clip.width}:${clip.height}:${clip.palette.join("")}`;
    if (b.key !== key) {
      if (b.session)
        await bridgeFetch(
          "/session",
          { method: "DELETE", body: JSON.stringify({ sessionId: b.session }) },
          b,
        );
      const session = await bridgeFetch(
        "/session",
        {
          method: "POST",
          body: JSON.stringify({
            width: clip.width,
            height: clip.height,
            palette: clip.palette,
          }),
        },
        b,
      );
      b.session = session.sessionId;
      b.key = key;
      b.sequence = 0;
    }
    if (state.bridge !== b) return;
    const result = await bridgeFetch(
      "/frame",
      {
        method: "POST",
        body: JSON.stringify({
          sessionId: b.session,
          sequence: b.sequence++,
          pixels: Array.from(pixels),
        }),
      },
      b,
    );
    if (state.bridge === b)
      $("bridge-status").textContent =
        `${b.mode === "simulation" ? "Simulation" : "Calc"} connected · ${result.changedCells.toLocaleString()} cells changed · ${Math.round(result.renderMs)} ms render time. Intermediate frames are dropped when Calc is busy.`;
  } catch (e) {
    if (state.bridge === b) {
      state.bridge = null;
      document.querySelector(".connection-dot").classList.remove("connected");
      $("disconnect-button").disabled = true;
      $("bridge-status").textContent = `Disconnected: ${e.message}`;
      toast(`Calc connection stopped: ${e.message}`, true);
    }
  } finally {
    b.busy = false;
    const pending = b.pending;
    b.pending = null;
    if (pending && state.bridge === b) sendNative(pending.clip, pending.pixels);
  }
}

$("file-input").addEventListener("change", (e) => {
  acceptFile(e.target.files[0]);
  e.target.value = "";
});
$("dropzone").addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    $("file-input").click();
  }
});
for (const event of ["dragenter", "dragover"])
  $("dropzone").addEventListener(event, (e) => {
    e.preventDefault();
    $("dropzone").classList.add("drag-over");
  });
for (const event of ["dragleave", "drop"])
  $("dropzone").addEventListener(event, (e) => {
    e.preventDefault();
    $("dropzone").classList.remove("drag-over");
  });
$("dropzone").addEventListener("drop", (e) =>
  acceptFile(e.dataTransfer.files[0]),
);
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());
document
  .querySelector('[role="tablist"]')
  .addEventListener("keydown", (event) => {
    if (
      !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) ||
      state.busy
    )
      return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? "file"
        : event.key === "End"
          ? "camera"
          : state.mode === "file"
            ? "camera"
            : "file";
    showMode(next);
    $(`${next}-tab`).focus();
  });
$("file-tab").onclick = () => showMode("file");
$("camera-tab").onclick = () => showMode("camera");
$("start-camera").onclick = startCamera;
$("stop-camera").onclick = () => {
  stopCamera();
  state.playing = true;
  configureClip(state.clip);
};
$("record-button").onclick = startRecording;
document.querySelectorAll(".palette-option").forEach(
  (button) =>
    (button.onclick = () => {
      state.palette = button.dataset.palette;
      document.querySelectorAll(".palette-option").forEach((b) => {
        b.classList.toggle("active", b === button);
        b.setAttribute("aria-pressed", String(b === button));
      });
      $("palette-count").textContent =
        `${makePalette(state.palette).length} colors`;
    }),
);
$("resolution").onchange = () => {
  const w = Number($("resolution").value);
  $("cell-count-label").textContent =
    `${(w * Math.round((w * 9) / 16)).toLocaleString()} cells`;
};
$("grid-toggle").onchange = draw;
$("convert-button").onclick = () => {
  if (state.stream) {
    toast("Live camera settings apply immediately.");
    return;
  }
  if (state.sourceKind === "recording" || state.sourceKind === "data") {
    try {
      configureClip(
        transformClip(state.originalClip, activeSettings()),
        state.originalClip.title,
      );
      state.playing = true;
      playbackButton();
      toast("Recording updated with your settings.");
    } catch (e) {
      toast(e.message, true);
    }
    return;
  }
  if (state.file) convertFile(state.file);
  else {
    const s = activeSettings();
    configureClip(
      createDemo(s.width, Math.round((s.width * 9) / 16), s.fps, s.mode),
    );
    state.playing = true;
    playbackButton();
    toast("Sample regenerated with your settings.");
  }
};
$("sample-button").onclick = () => {
  stopCamera();
  state.file = null;
  state.sourceKind = "demo";
  state.originalClip = null;
  const s = activeSettings();
  state.playing = true;
  configureClip(
    createDemo(s.width, Math.round((s.width * 9) / 16), s.fps, s.mode),
  );
  $("source-name").textContent = "Blue hour";
  $("source-detail").textContent = "Sample animation · 6 seconds";
};
$("cancel-convert").onclick = () => {
  if ($("cancel-convert").disabled) return;
  $("cancel-convert").disabled = true;
  state.job++;
  state.abort?.abort();
  $("progress-label").textContent = "Cancelling…";
};
$("play-button").onclick = () => {
  if (state.stream) {
    toast("Turn off the camera to review the recorded clip.");
    return;
  }
  state.playing = !state.playing;
  state.lastTick = 0;
  playbackButton();
};
$("restart-button").onclick = () => {
  state.frame = 0;
  state.lastTick = 0;
  draw();
  sendNative();
};
$("step-button").onclick = () => {
  if (state.stream) return;
  state.playing = false;
  state.frame = (state.frame + 1) % state.clip.frames.length;
  playbackButton();
  draw();
  sendNative();
};
$("timeline").oninput = () => {
  if (state.stream) return;
  state.playing = false;
  state.frame = Number($("timeline").value);
  playbackButton();
  draw();
  sendNative();
};
$("loop-button").onclick = () => {
  state.loop = !state.loop;
  $("loop-button").classList.toggle("active", state.loop);
  $("loop-button").setAttribute("aria-pressed", String(state.loop));
};
$("fullscreen-button").onclick = async () => {
  try {
    await $("canvas-wrap").requestFullscreen();
  } catch {
    toast("Full screen is not available in this browser.", true);
  }
};
$("export-button").onclick = exportOds;
$("json-button").onclick = () => {
  try {
    download(
      new Blob([serializeClip(exportableClip())], { type: "application/json" }),
      safeName() + ".celluloid.json",
    );
    toast("Frame data downloaded. Import it later to restore this animation.");
  } catch (e) {
    toast(e.message, true);
  }
};
$("cli-button").onclick = () => $("cli-dialog").showModal();
$("how-button").onclick = () => $("help-dialog").showModal();
$("native-button").onclick = () => $("native-dialog").showModal();
document
  .querySelectorAll(".close-dialog")
  .forEach((b) => (b.onclick = () => b.closest("dialog").close()));
for (const dialog of document.querySelectorAll("dialog"))
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) {
      const r = dialog.getBoundingClientRect();
      if (
        e.clientX < r.left ||
        e.clientX > r.right ||
        e.clientY < r.top ||
        e.clientY > r.bottom
      )
        dialog.close();
    }
  });
$("connect-button").onclick = connectBridge;
$("disconnect-button").onclick = () => disconnectBridge();
$("download-source").onclick = () => {
  const a = document.createElement("a");
  a.href = "downloads/toolkit.zip";
  a.download = "celluloid-toolkit.zip";
  a.click();
};
if (location.port === "8765") $("bridge-url").value = location.origin;
new ResizeObserver(draw).observe($("canvas-wrap"));
document.addEventListener("keydown", (e) => {
  if (
    e.code === "Space" &&
    !["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(
      document.activeElement.tagName,
    ) &&
    !document.querySelector("dialog[open]")
  ) {
    e.preventDefault();
    $("play-button").click();
  }
});
window.addEventListener("pagehide", () => {
  state.stream?.getTracks().forEach((t) => t.stop());
  if (state.url) URL.revokeObjectURL(state.url);
});
setWorld(document.documentElement.dataset.world || "nerdy");
for (const button of document.querySelectorAll("[data-world-button]"))
  button.onclick = () => {
    setWorld(button.dataset.worldButton);
    if (state.stream) cameraFrame();
    else draw();
  };
configureClip(state.clip);
cameraStatus(
  "Click Enable camera to request access. Your browser and operating system must both allow the camera.",
);
requestAnimationFrame(tick);
