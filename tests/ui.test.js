import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { JSDOM } from "jsdom";

test("studio interactions, mocked media lifecycle and companion protocol", async (t) => {
  const nativeTimeout = globalThis.setTimeout;
  globalThis.setTimeout = (fn, ms, ...args) => {
    const timer = nativeTimeout(fn, ms, ...args);
    if (ms > 1000) timer.unref?.();
    return timer;
  };
  const html = await readFile(
    new URL("../dist/index.html", import.meta.url),
    "utf8",
  );
  const dom = new JSDOM(html, { url: "http://localhost:5173" }),
    window = dom.window,
    $ = (id) => window.document.getElementById(id);
  let loop;
  const painted = [];
  const drawContext = {
    setTransform() {},
    clearRect() {},
    fillRect(...r) {
      painted.push(r);
    },
    beginPath() {},
    moveTo() {},
    lineTo() {},
    stroke() {},
    fill() {},
    fillText() {},
    save() {},
    restore() {},
    translate() {},
    scale() {},
    drawImage() {},
    getImageData(x, y, w, h) {
      return { data: new Uint8ClampedArray(w * h * 4).fill(255) };
    },
  };
  window.HTMLCanvasElement.prototype.getContext = () => drawContext;
  window.HTMLCanvasElement.prototype.getBoundingClientRect = () => ({
    width: 850,
    height: 500,
  });
  window.HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  window.HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  let currentTime = 0,
    decode = true,
    readiness = 2,
    delayedFirstFrame = false,
    stopped = 0,
    downloads = [];
  const video = $("source-video");
  Object.defineProperties(video, {
    videoWidth: { get: () => 1280 },
    videoHeight: { get: () => 720 },
    duration: { get: () => 2 },
    readyState: { get: () => readiness },
    currentTime: {
      get: () => currentTime,
      set: (v) => {
        const changed = currentTime !== v;
        currentTime = v;
        if (decode && (!delayedFirstFrame || changed))
          queueMicrotask(() => video.dispatchEvent(new window.Event("seeked")));
      },
    },
  });
  video.load = () => {
    currentTime = 0;
    readiness = delayedFirstFrame ? 1 : 2;
    if (decode)
      queueMicrotask(() =>
        video.dispatchEvent(new window.Event("loadedmetadata")),
      );
    if (decode && delayedFirstFrame)
      setTimeout(() => {
        readiness = 2;
        video.dispatchEvent(new window.Event("loadeddata"));
      }, 10);
  };
  video.pause = () => {};
  video.play = async () => {
    readiness = 2;
  };
  const track = {
    stop() {
      stopped++;
    },
    addEventListener() {},
  };
  let denyCamera = false,
    cameraErrorName = null,
    cameraPending = null,
    cameraCalls = 0;
  const navigator = {
    mediaDevices: {
      async getUserMedia() {
        cameraCalls++;
        if (cameraPending) return cameraPending;
        if (cameraErrorName)
          throw Object.assign(Error("Camera unavailable"), {
            name: cameraErrorName,
          });
        if (denyCamera)
          throw Object.assign(Error("Denied"), { name: "NotAllowedError" });
        return { getTracks: () => [track], getVideoTracks: () => [track] };
      },
    },
  };
  const urlClass = class extends URL {
    static createObjectURL(blob) {
      downloads.push(blob);
      return "blob:mock";
    }
    static revokeObjectURL() {}
  };
  Object.assign(globalThis, {
    window,
    document: window.document,
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: (fn) => {
      loop = fn;
    },
    ResizeObserver: class {
      observe() {}
    },
    devicePixelRatio: 1,
    location: window.location,
    URL: urlClass,
  });
  Object.defineProperty(globalThis, "navigator", {
    value: navigator,
    configurable: true,
  });
  window.isSecureContext = true;
  window.HTMLAnchorElement.prototype.click = function () {};
  await import("../dist/app.js");
  const flush = () => new Promise((r) => setTimeout(r, 20));
  await t.test(
    "world switching preserves media data and announces the selected world",
    async () => {
      $("json-button").click();
      const before = await downloads.at(-1).text();
      window.document.querySelector("[data-world-button=creative]").click();
      assert.equal(window.document.documentElement.dataset.world, "creative");
      assert.equal(window.localStorage.getItem("celluloid-world"), "creative");
      assert.equal(
        window.document
          .querySelector("[data-world-button=creative]")
          .getAttribute("aria-pressed"),
        "true",
      );
      $("json-button").click();
      assert.equal(await downloads.at(-1).text(), before);
      window.document.querySelector("[data-world-button=nerdy]").click();
      $("cli-button").click();
      assert.equal($("cli-dialog").open, true);
      $("cli-dialog").close();
    },
  );
  await t.test(
    "initial sample renders and playback controls change frame",
    () => {
      assert.equal($("stats-size").textContent, "64 × 36");
      assert.ok(painted.length > 2000);
      loop(200);
      assert.equal($("timeline").value, "1");
      $("play-button").click();
      const before = $("timeline").value;
      loop(400);
      assert.equal($("timeline").value, before);
      $("step-button").click();
      assert.equal(Number($("timeline").value), Number(before) + 1);
      $("restart-button").click();
      assert.equal($("timeline").value, "0");
    },
  );
  await t.test("palette and resolution apply to the sample", () => {
    $("resolution").value = "48";
    window.document.querySelector("[data-palette=mono]").click();
    $("convert-button").click();
    assert.equal($("stats-size").textContent, "48 × 27");
    assert.equal($("palette-count").textContent, "2 colors");
  });
  await t.test(
    "upload waits for the decoded first frame after metadata",
    async () => {
      delayedFirstFrame = true;
      try {
        const input = $("file-input");
        Object.defineProperty(input, "files", {
          value: [
            { name: "delayed-first-frame.mp4", type: "video/mp4", size: 1024 },
          ],
          configurable: true,
        });
        input.dispatchEvent(new window.Event("change"));
        await flush();
        await flush();
        assert.equal($("source-name").textContent, "delayed-first-frame.mp4");
        assert.equal($("canvas-overlay").hidden, true);
        assert.equal($("stats-frames").textContent, "16 frames");
      } finally {
        delayedFirstFrame = false;
      }
    },
  );
  await t.test(
    "file upload converts seeked media frames and exports",
    async () => {
      const input = $("file-input");
      Object.defineProperty(input, "files", {
        value: [{ name: "test.mp4", type: "video/mp4", size: 1024 }],
        configurable: true,
      });
      input.dispatchEvent(new window.Event("change"));
      await flush();
      await flush();
      assert.equal($("source-name").textContent, "test.mp4");
      assert.equal($("stats-frames").textContent, "16 frames");
      assert.equal($("canvas-overlay").hidden, true);
      $("json-button").click();
      assert.equal(downloads.at(-1).type, "application/json");
      $("export-button").click();
      await new Promise((r) => setTimeout(r, 60));
      assert.equal(
        downloads.at(-1).type,
        "application/vnd.oasis.opendocument.spreadsheet",
      );
      assert.equal($("help-dialog").open, true);
      $("help-dialog").close();
    },
  );
  await t.test(
    "repeated cancellation cannot leave the studio disabled",
    async () => {
      decode = false;
      $("convert-button").click();
      assert.equal($("canvas-overlay").hidden, false);
      $("cancel-convert").click();
      $("cancel-convert").click();
      await flush();
      assert.equal($("canvas-overlay").hidden, true);
      assert.equal($("convert-button").disabled, false);
      decode = true;
    },
  );
  await t.test(
    "insecure pages show a persistent camera error without requesting access",
    async () => {
      $("camera-tab").click();
      const calls = cameraCalls;
      window.isSecureContext = false;
      try {
        $("start-camera").click();
        await flush();
        assert.equal(cameraCalls, calls);
        assert.match($("camera-status").textContent, /HTTPS or localhost/);
        assert.equal($("camera-help").open, true);
      } finally {
        window.isSecureContext = true;
      }
    },
  );
  await t.test(
    "permissions-policy blocks are explained before requesting a camera",
    async () => {
      const calls = cameraCalls;
      Object.defineProperty(window.document, "permissionsPolicy", {
        value: { allowsFeature: () => false },
        configurable: true,
      });
      try {
        $("start-camera").click();
        await flush();
        assert.equal(cameraCalls, calls);
        assert.match(
          $("camera-status").textContent,
          /permissions policy blocks/,
        );
      } finally {
        delete window.document.permissionsPolicy;
      }
    },
  );
  await t.test(
    "a pending camera request is visible and a late grant after source change is released",
    async () => {
      let grant;
      cameraPending = new Promise((resolve) => {
        grant = resolve;
      });
      const calls = cameraCalls,
        previousStops = stopped;
      $("start-camera").click();
      assert.equal(
        cameraCalls,
        calls + 1,
        "getUserMedia is called directly from the Enable camera click",
      );
      assert.equal($("start-camera").disabled, true);
      assert.match($("start-camera").textContent, /Requesting camera/);
      assert.match($("camera-status").textContent, /permission indicator/);
      $("file-tab").click();
      grant({ getTracks: () => [track], getVideoTracks: () => [track] });
      cameraPending = null;
      await flush();
      assert.equal(stopped, previousStops + 1);
      assert.equal($("start-camera").disabled, false);
      assert.equal(video.srcObject, null);
      assert.match($("camera-status").textContent, /source changed/);
      $("camera-tab").click();
    },
  );
  await t.test(
    "a busy camera shows a persistent actionable error",
    async () => {
      cameraErrorName = "NotReadableError";
      try {
        $("start-camera").click();
        await flush();
        assert.match($("camera-status").textContent, /busy or unavailable/);
        assert.equal($("camera-help").open, true);
        assert.equal($("start-camera").disabled, false);
      } finally {
        cameraErrorName = null;
      }
    },
  );
  await t.test(
    "camera permission denial is recoverable; granted tracks stop",
    async () => {
      $("camera-tab").click();
      denyCamera = true;
      $("start-camera").click();
      await flush();
      assert.match($("toast").textContent, /permission was denied/);
      assert.match($("camera-status").textContent, /Arc\/Chromium/);
      assert.match($("camera-status").textContent, /System Settings/);
      assert.equal($("start-camera").disabled, false);
      denyCamera = false;
      $("start-camera").click();
      await flush();
      assert.equal($("live-label").hidden, false);
      assert.match($("camera-status").textContent, /Camera is live/);
      loop(1000);
      $("record-button").click();
      loop(1200);
      loop(1400);
      $("record-button").click();
      assert.match($("record-status").textContent, /Captured/);
      $("stop-camera").click();
      assert.ok(stopped >= 1);
      assert.equal($("live-label").hidden, true);
      assert.equal(video.srcObject, null);
      assert.equal($("source-name").textContent, "Webcam recording");
      $("resolution").value = "32";
      $("convert-button").click();
      assert.equal($("source-name").textContent, "Webcam recording");
      assert.equal($("stats-size").textContent, "32 × 18");
    },
  );
  await t.test(
    "native pairing sends indexed frames and retains latest paused seek",
    async () => {
      const calls = [];
      let release;
      globalThis.fetch = async (url, options = {}) => {
        const body = options.body ? JSON.parse(options.body) : null;
        calls.push({ url, body, method: options.method });
        if (url.endsWith("/health"))
          return {
            ok: true,
            json: async () => ({
              protocol: "cell-video-v1",
              mode: "simulation",
            }),
          };
        if (url.endsWith("/session") && options.method === "POST")
          return {
            ok: true,
            json: async () => ({ sessionId: "test-session" }),
          };
        if (url.endsWith("/frame")) {
          if (calls.filter((c) => c.url.endsWith("/frame")).length === 1)
            await new Promise((r) => (release = r));
          return {
            ok: true,
            json: async () => ({ changedCells: 1, renderMs: 1 }),
          };
        }
        return { ok: true, json: async () => ({ stopped: true }) };
      };
      $("bridge-token").value = "test-pairing-token";
      $("connect-button").click();
      await flush();
      $("step-button").click();
      $("step-button").click();
      release();
      await flush();
      await flush();
      const frames = calls.filter((c) => c.url.endsWith("/frame"));
      assert.ok(frames.length >= 2);
      assert.ok(Array.isArray(frames[0].body.pixels));
      assert.ok(frames.at(-1).body.sequence > frames[0].body.sequence);
      assert.match($("bridge-status").textContent, /Simulation/);
      $("disconnect-button").click();
      await flush();
      assert.ok(calls.some((c) => c.method === "DELETE"));
    },
  );
  dom.window.close();
  globalThis.setTimeout = nativeTimeout;
});
