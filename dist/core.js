export const LIMITS = { frames: 240, cells: 14400, file: 100 * 1024 * 1024 };
export function columnName(n) {
  let s = "";
  for (n++; n > 0; n = Math.floor((n - 1) / 26))
    s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
  return s;
}
export function makePalette(mode = "color") {
  if (mode === "mono") return ["#171c24", "#f8f4e9"];
  if (mode === "grayscale")
    return Array.from(
      { length: 16 },
      (_, i) => "#" + (i * 17).toString(16).padStart(2, "0").repeat(3),
    );
  return Array.from(
    { length: 216 },
    (_, i) =>
      "#" +
      [Math.floor(i / 36) * 51, (Math.floor(i / 6) % 6) * 51, (i % 6) * 51]
        .map((v) => v.toString(16).padStart(2, "0"))
        .join(""),
  );
}
export function quantize(rgba, mode = "color") {
  const out = new Uint8Array(rgba.length / 4);
  for (let i = 0, j = 0; i < rgba.length; i += 4, j++) {
    const r = rgba[i],
      g = rgba[i + 1],
      b = rgba[i + 2];
    out[j] =
      mode === "color"
        ? Math.round(r / 51) * 36 + Math.round(g / 51) * 6 + Math.round(b / 51)
        : mode === "mono"
          ? +(r * 0.2126 + g * 0.7152 + b * 0.0722 >= 128)
          : Math.round((r * 0.2126 + g * 0.7152 + b * 0.0722) / 17);
  }
  return out;
}
export function validateClip(clip) {
  if (
    clip?.version !== 1 ||
    !Number.isInteger(clip.width) ||
    !Number.isInteger(clip.height) ||
    clip.width < 1 ||
    clip.width > 160 ||
    clip.height < 1 ||
    clip.height > 90 ||
    clip.width * clip.height > LIMITS.cells
  )
    throw Error("Invalid grid dimensions. Maximum grid is 160 × 90.");
  if (!Number.isFinite(clip.fps) || clip.fps < 1 || clip.fps > 30)
    throw Error("Invalid frame rate.");
  if (
    !Array.isArray(clip.palette) ||
    clip.palette.length < 1 ||
    clip.palette.length > 256 ||
    clip.palette.some((c) => !/^#[0-9a-f]{6}$/i.test(c))
  )
    throw Error("Invalid color palette.");
  if (
    !Array.isArray(clip.frames) ||
    clip.frames.length < 1 ||
    clip.frames.length > LIMITS.frames
  )
    throw Error("A clip must have between 1 and 240 frames.");
  const count = clip.width * clip.height;
  for (const f of clip.frames)
    if (
      (!Array.isArray(f) && !ArrayBuffer.isView(f)) ||
      f.length !== count ||
      Array.from(f).some(
        (p) => !Number.isInteger(p) || p < 0 || p >= clip.palette.length,
      )
    )
      throw Error("Invalid frame data.");
  return clip;
}
export function serializeClip(clip) {
  validateClip(clip);
  return JSON.stringify({
    ...clip,
    frames: clip.frames.map((f) => Array.from(f)),
  });
}
export function transformClip(
  source,
  { width, fps, mode, duration = 10, start = 0 },
) {
  validateClip(source);
  let height = Math.max(1, Math.round((width * source.height) / source.width));
  if (height > 90) {
    height = 90;
    width = Math.max(1, Math.round((height * source.width) / source.height));
  }
  const available = source.frames.length / source.fps;
  if (start >= available)
    throw Error("Start time is beyond the end of this recording.");
  const count = Math.max(
      1,
      Math.min(
        LIMITS.frames,
        Math.ceil(Math.min(duration, available - start) * fps),
      ),
    ),
    palette = makePalette(mode),
    frames = [];
  const rgbPalette = source.palette.map((hex) =>
    [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16)),
  );
  for (let n = 0; n < count; n++) {
    const frame =
        source.frames[
          Math.min(
            source.frames.length - 1,
            Math.floor((start + n / fps) * source.fps),
          )
        ],
      rgba = new Uint8ClampedArray(width * height * 4);
    for (let y = 0; y < height; y++)
      for (let x = 0; x < width; x++) {
        const pixel =
          frame[
            Math.min(
              source.height - 1,
              Math.floor((y * source.height) / height),
            ) *
              source.width +
              Math.min(source.width - 1, Math.floor((x * source.width) / width))
          ];
        rgba.set([...rgbPalette[pixel], 255], (y * width + x) * 4);
      }
    frames.push(quantize(rgba, mode));
  }
  return {
    version: 1,
    width,
    height,
    fps,
    palette,
    frames,
    duration: count / fps,
    title: source.title,
  };
}
export function createDemo(width = 64, height = 36, fps = 8, mode = "color") {
  const palette = makePalette(mode),
    frames = [];
  for (let frame = 0; frame < fps * 6; frame++) {
    const rgba = new Uint8ClampedArray(width * height * 4),
      t = frame / fps;
    for (let y = 0; y < height; y++)
      for (let x = 0; x < width; x++) {
        const u = x / width,
          v = y / height;
        let rgb;
        if (v < 0.62) {
          const k = v / 0.62;
          rgb = [22 + 105 * k, 35 + 63 * k, 76 + 50 * k];
        } else {
          const k = (v - 0.62) / 0.38;
          rgb = [130 - 87 * k, 91 - 57 * k, 121 - 47 * k];
        }
        const sx = 0.69 + 0.025 * Math.sin(t * 0.5),
          sy = 0.34;
        if ((u - sx) ** 2 + (v - sy) ** 2 < 0.012) rgb = [255, 190, 104];
        if (
          v > 0.62 &&
          Math.abs(u - sx) < 0.025 + (v - 0.62) * 0.28 &&
          Math.sin(y * 2 + t * 3) > 0.1
        )
          rgb = [231, 151, 130];
        const mountain =
          0.58 - 0.16 * Math.sin(u * 7.5) - 0.045 * Math.sin(u * 25);
        if (v > mountain && v < 0.64) rgb = [68, 66, 105];
        const front =
          0.75 - 0.1 * Math.sin(u * 5 + 2) - 0.04 * Math.cos(u * 17);
        if (v > front) rgb = [27, 42, 65];
        if (v > 0.89 + 0.04 * Math.sin(u * 8)) rgb = [17, 31, 48];
        const bx = ((t * 0.07 + 0.1) % 1.4) - 0.2,
          by = 0.64;
        if (v > by && v < by + 0.025 && u > bx && u < bx + 0.1)
          rgb = [245, 180, 133];
        if (u > bx + 0.045 && u < bx + 0.054 && v > by - 0.1 && v < by)
          rgb = [247, 229, 193];
        if (
          u > bx + 0.054 &&
          u < bx + 0.105 &&
          v > by - 0.09 + (u - bx - 0.054) * 1.5 &&
          v < by - 0.01
        )
          rgb = [227, 108, 78];
        if (v < 0.3 && Math.sin(x * 127.1 + y * 311.7) > 0.992)
          rgb = [219, 215, 203];
        rgba.set([...rgb, 255], (y * width + x) * 4);
      }
    frames.push(quantize(rgba, mode));
  }
  return {
    version: 1,
    width,
    height,
    fps,
    palette,
    frames,
    duration: 6,
    title: "Blue hour — sample animation",
  };
}
