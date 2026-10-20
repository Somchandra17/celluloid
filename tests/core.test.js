import test from "node:test";
import assert from "node:assert/strict";
import {
  columnName,
  makePalette,
  quantize,
  createDemo,
  validateClip,
  serializeClip,
  transformClip,
} from "../dist/core.js";
import { createOds } from "../dist/ods.js";

test("spreadsheet column naming crosses alphabet boundaries", () => {
  assert.deepEqual([0, 25, 26, 51, 52, 63, 95].map(columnName), [
    "A",
    "Z",
    "AA",
    "AZ",
    "BA",
    "BL",
    "CR",
  ]);
});
test("color quantization maps decoded RGB to exported palette colors", () => {
  const rgba = new Uint8ClampedArray([
    255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255,
  ]);
  const palette = makePalette();
  assert.equal(palette.length, 216);
  assert.deepEqual(
    [...quantize(rgba)].map((i) => palette[i]),
    ["#ff0000", "#00ff00", "#0000ff", "#ffffff"],
  );
  assert.deepEqual([...quantize(rgba, "mono")], [0, 1, 0, 1]);
  assert.equal(makePalette("grayscale").length, 16);
});
test("sample is a bounded changing animation and frame data round-trips", () => {
  const clip = createDemo(64, 36, 8);
  assert.equal(clip.frames.length, 48);
  assert.equal(clip.frames[0].length, 2304);
  assert.notDeepEqual(clip.frames[0], clip.frames[20]);
  assert.equal(validateClip(JSON.parse(serializeClip(clip))).frames.length, 48);
});
test("malformed frame data is rejected before rendering or export", () => {
  const good = createDemo(8, 5, 4);
  for (const patch of [
    { width: 0 },
    { height: 100 },
    { fps: 0 },
    { palette: ["red"] },
    { frames: [] },
    { frames: [null] },
    { frames: [new Array(40).fill(999)] },
  ])
    assert.throws(() => validateClip({ ...good, ...patch }));
});
test("browser export yields a real ZIP ODS with document and embedded playback", async () => {
  const blob = createOds(createDemo(8, 5, 4));
  assert.equal(blob.type, "application/vnd.oasis.opendocument.spreadsheet");
  const bytes = new Uint8Array(await blob.arrayBuffer());
  assert.equal(new TextDecoder().decode(bytes.slice(0, 2)), "PK");
  const text = new TextDecoder().decode(bytes);
  assert.match(text, /fo:background-color/);
  assert.match(text, /Sub PlayVideo/);
  assert.match(text, /CellBackColor/);
});

test("recorded clips can be resized and recolored without replacing their content", () => {
  const clip = createDemo(64, 36, 8);
  const output = transformClip(clip, {
    width: 48,
    fps: 4,
    mode: "mono",
    duration: 5,
    start: 1,
  });
  assert.equal(output.frames.length, 20);
  assert.equal(output.width, 48);
  assert.equal(output.height, 27);
  assert.equal(output.palette.length, 2);
  assert.throws(() =>
    transformClip(clip, { width: 48, fps: 4, mode: "color", start: 999 }),
  );
});
