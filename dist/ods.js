/** Portable OpenDocument export. Real Calc cell fills; no images or external dependencies. */
export const ODS_LIMITS = Object.freeze({
  maxWidth: 96,
  maxHeight: 54,
  maxFrames: 240,
});
const MIME = "application/vnd.oasis.opendocument.spreadsheet";
const enc = new TextEncoder();
const xml = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&apos;",
      })[c],
  );
const NS =
  'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" xmlns:xlink="http://www.w3.org/1999/xlink"';

/** Kept human-readable in the ZIP so users can inspect the code before enabling macros. */
export const PLAYER_BASIC = `REM Celluloid: this module only reads this document and changes its cell fills.
Option Explicit
Global CelluloidPlaying As Boolean

Sub StopVideo
  CelluloidPlaying = False
End Sub

Sub PlayVideo
  Dim doc As Object, video As Object, data As Object
  Dim frame As Long, total As Long, w As Long, h As Long, fps As Double
  Dim chunk As Long, chunks As Long, colors As String
  Dim y As Long, x As Long, startX As Long, offset As Long
  Dim color As Long, nextColor As Long, started As Double, elapsed As Double, delay As Long
  Dim locked As Boolean
  If CelluloidPlaying Then Exit Sub
  On Error GoTo Failed
  doc = ThisComponent
  video = doc.Sheets.getByName("Video")
  data = doc.Sheets.getByName("_Frames")
  w = data.getCellByPosition(0, 0).Value
  h = data.getCellByPosition(1, 0).Value
  fps = data.getCellByPosition(2, 0).Value
  total = data.getCellByPosition(3, 0).Value
  If w < 1 Or w > 96 Or h < 1 Or h > 54 Or total < 1 Or total > 240 Or fps < 1 Or fps > 30 Then Exit Sub
  chunks = Int((w * h + 511) / 512)
  doc.CurrentController.setActiveSheet(video)
  CelluloidPlaying = True
  For frame = 1 To total
    If Not CelluloidPlaying Then Exit For
    started = Timer
    colors = ""
    For chunk = 0 To chunks - 1
      colors = colors & data.getCellByPosition(chunk, frame).String
    Next chunk
    If Len(colors) <> w * h * 6 Then GoTo Failed
    doc.lockControllers
    locked = True
    For y = 0 To h - 1
      x = 0
      Do While x < w
        startX = x
        offset = (y * w + x) * 6 + 1
        color = CLng("&H" & Mid(colors, offset, 6))
        x = x + 1
        Do While x < w
          nextColor = CLng("&H" & Mid(colors, (y * w + x) * 6 + 1, 6))
          If nextColor <> color Then Exit Do
          x = x + 1
        Loop
        video.getCellRangeByPosition(startX, y, x - 1, y).CellBackColor = color
      Loop
    Next y
    doc.unlockControllers
    locked = False
    elapsed = Timer - started
    If elapsed < 0 Then elapsed = elapsed + 86400
    delay = CLng(1000 / fps - elapsed * 1000)
    If delay < 1 Then delay = 1
    Wait delay
  Next frame
  CelluloidPlaying = False
  Exit Sub
Failed:
  If locked Then doc.unlockControllers
  CelluloidPlaying = False
  MsgBox "Playback stopped. Reopen the original Celluloid export if its frame data was edited.", 48, "Celluloid"
End Sub`;

function normalizeColor(color) {
  if (Array.isArray(color) || ArrayBuffer.isView(color)) {
    if (color.length < 3)
      throw new Error("Palette colors need red, green and blue values.");
    return Array.from(color)
      .slice(0, 3)
      .map((v) => {
        if (!Number.isInteger(v) || v < 0 || v > 255)
          throw new Error("Invalid palette channel.");
        return v.toString(16).padStart(2, "0");
      })
      .join("");
  }
  const value = String(color).replace(/^#/, "");
  if (!/^[0-9a-f]{6}$/i.test(value))
    throw new Error("Palette colors must use six-digit RGB hex.");
  return value.toLowerCase();
}

function validate({ width, height, fps = 8, frames, palette }) {
  if (
    !Number.isInteger(width) ||
    width < 1 ||
    width > ODS_LIMITS.maxWidth ||
    !Number.isInteger(height) ||
    height < 1 ||
    height > ODS_LIMITS.maxHeight
  )
    throw new Error("ODS export supports grids up to 96 × 54 cells.");
  if (!Number.isFinite(fps) || fps < 1 || fps > 30)
    throw new Error("Choose a frame rate between 1 and 30.");
  if (
    !Array.isArray(frames) ||
    frames.length < 1 ||
    frames.length > ODS_LIMITS.maxFrames
  )
    throw new Error("ODS export needs between 1 and 240 frames.");
  if (!Array.isArray(palette) || !palette.length || palette.length > 256)
    throw new Error("Provide a palette containing 1 to 256 colors.");
  const colors = palette.map(normalizeColor);
  const count = width * height;
  for (const frame of frames) {
    if (!frame || frame.length !== count)
      throw new Error("Frame dimensions do not match the grid.");
    for (let i = 0; i < count; i++) {
      if (
        !Number.isInteger(frame[i]) ||
        frame[i] < 0 ||
        frame[i] >= colors.length
      )
        throw new Error("A frame contains an invalid palette index.");
    }
  }
  return { width, height, fps, frames, colors };
}

function cellText(value) {
  return `<table:table-cell office:value-type="string"><text:p>${xml(value)}</text:p></table:table-cell>`;
}
function cellNumber(value) {
  return `<table:table-cell office:value-type="float" office:value="${value}"><text:p>${value}</text:p></table:table-cell>`;
}

function content({ width, height, fps, frames, colors }) {
  const styles = colors
    .map(
      (color, i) =>
        `<style:style style:name="p${i}" style:family="table-cell"><style:table-cell-properties fo:background-color="#${color}" fo:padding="0in"/></style:style>`,
    )
    .join("");
  const pixels = [];
  for (let y = 0; y < height; y++) {
    let row = '<table:table-row table:style-name="pixelRow">';
    for (let x = 0; x < width; ) {
      const index = frames[0][y * width + x];
      let run = 1;
      while (x + run < width && frames[0][y * width + x + run] === index) run++;
      row += `<table:table-cell table:style-name="p${index}"${run > 1 ? ` table:number-columns-repeated="${run}"` : ""}/>`;
      x += run;
    }
    pixels.push(row + "</table:table-row>");
  }
  const notes = [
    "CELLULOID / video through real spreadsheet cells",
    "The Video sheet contains actual colored cells. Its first frame is visible immediately.",
    "PLAY: Tools → Macros → Run Macro → this document → Standard → Playback → PlayVideo → Run.",
    "Playback code is embedded in this file. LibreOffice may block macros; review the code before trusting the document.",
    "Use a trusted document/location according to your own macro policy. Do not lower global macro security.",
    "StopVideo stops playback; Escape may interrupt Basic. Clips play once; run PlayVideo again to replay.",
    "Requested timing is best effort: Calc cell formatting is slower than the browser preview. Audio is not included.",
    `${width} × ${height} cells · ${frames.length} frames · ${fps} requested frames/second`,
    "The hidden _Frames sheet stores RGB colors. No network access, images or external files are used by the player.",
    "For live webcam playback in Calc, use the optional local Celluloid bridge. An ODS export is a recorded clip.",
  ];
  const instructions = notes
    .map((note) => `<table:table-row>${cellText(note)}</table:table-row>`)
    .join("");
  const stored = [
    `<table:table-row>${[width, height, fps, frames.length].map(cellNumber).join("")}</table:table-row>`,
  ];
  for (const frame of frames) {
    const parts = [];
    for (let start = 0; start < frame.length; start += 512) {
      let value = "";
      for (let i = start; i < Math.min(start + 512, frame.length); i++)
        value += colors[frame[i]];
      parts.push(cellText(value));
    }
    stored.push(`<table:table-row>${parts.join("")}</table:table-row>`);
  }
  return `<?xml version="1.0" encoding="UTF-8"?><office:document-content ${NS} office:version="1.3"><office:scripts/><office:automatic-styles>${styles}<style:style style:name="pixelColumn" style:family="table-column"><style:table-column-properties style:column-width="0.10in"/></style:style><style:style style:name="pixelRow" style:family="table-row"><style:table-row-properties style:row-height="0.10in" style:use-optimal-row-height="false"/></style:style><style:style style:name="hidden" style:family="table"><style:table-properties table:display="false"/></style:style><style:style style:name="noteColumn" style:family="table-column"><style:table-column-properties style:column-width="10in"/></style:style></office:automatic-styles><office:body><office:spreadsheet><table:table table:name="Video"><table:table-column table:style-name="pixelColumn" table:number-columns-repeated="${width}"/>${pixels.join("")}</table:table><table:table table:name="Instructions"><table:table-column table:style-name="noteColumn"/>${instructions}</table:table><table:table table:name="_Frames" table:style-name="hidden">${stored.join("")}</table:table></office:spreadsheet></office:body></office:document-content>`;
}

let crcTable;
function crc32(bytes) {
  if (!crcTable)
    crcTable = Uint32Array.from({ length: 256 }, (_, n) => {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      return c >>> 0;
    });
  let crc = 0xffffffff;
  for (const byte of bytes) crc = crcTable[(crc ^ byte) & 255] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}
function header(size, values) {
  const bytes = new Uint8Array(size),
    view = new DataView(bytes.buffer);
  for (const [offset, value, bits] of values)
    bits === 16
      ? view.setUint16(offset, value, true)
      : view.setUint32(offset, value, true);
  return bytes;
}
/** ZIP method STORE is intentional: ODF requires its first mimetype entry uncompressed. */
function zip(entries) {
  const local = [],
    central = [];
  let offset = 0,
    centralSize = 0;
  for (const [filename, value] of entries) {
    const name = enc.encode(filename),
      data = enc.encode(value),
      crc = crc32(data);
    const h = header(30, [
      [0, 0x04034b50],
      [4, 20, 16],
      [6, 0x800, 16],
      [8, 0, 16],
      [12, 33, 16],
      [14, crc],
      [18, data.length],
      [22, data.length],
      [26, name.length, 16],
    ]);
    const c = header(46, [
      [0, 0x02014b50],
      [4, 20, 16],
      [6, 20, 16],
      [8, 0x800, 16],
      [10, 0, 16],
      [14, 33, 16],
      [16, crc],
      [20, data.length],
      [24, data.length],
      [28, name.length, 16],
      [42, offset],
    ]);
    local.push(h, name, data);
    central.push(c, name);
    offset += h.length + name.length + data.length;
    centralSize += c.length + name.length;
  }
  const end = header(22, [
    [0, 0x06054b50],
    [8, entries.length, 16],
    [10, entries.length, 16],
    [12, centralSize],
    [16, offset],
  ]);
  return new Blob([...local, ...central, end], { type: MIME });
}

/** Indexed frames are arrays/Uint8Arrays of width*height palette indices. */
export function createOds(options) {
  const data = validate(options);
  const title = options.title || "Celluloid clip";
  const module = `<?xml version="1.0" encoding="UTF-8"?><script:module xmlns:script="http://openoffice.org/2000/script" script:name="Playback" script:language="StarBasic">${xml(PLAYER_BASIC)}</script:module>`;
  const libraryNs =
    'xmlns:library="http://openoffice.org/2000/library" xmlns:xlink="http://www.w3.org/1999/xlink"';
  const entries = [
    ["mimetype", MIME],
    ["content.xml", content(data)],
    [
      "styles.xml",
      `<?xml version="1.0"?><office:document-styles ${NS} office:version="1.3"><office:styles><style:default-style style:family="table-cell"><style:table-cell-properties fo:padding="0in"/></style:default-style></office:styles></office:document-styles>`,
    ],
    [
      "meta.xml",
      `<?xml version="1.0"?><office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:dc="http://purl.org/dc/elements/1.1/" office:version="1.3"><office:meta><dc:title>${xml(title)}</dc:title><dc:description>Celluloid video rendered as real colored spreadsheet cells.</dc:description></office:meta></office:document-meta>`,
    ],
    [
      "Basic/script-lc.xml",
      `<?xml version="1.0"?><library:libraries ${libraryNs}><library:library library:name="Standard" library:link="false"/></library:libraries>`,
    ],
    [
      "Basic/Standard/script-lb.xml",
      `<?xml version="1.0"?><library:library ${libraryNs} library:name="Standard" library:readonly="false" library:passwordprotected="false"><library:element library:name="Playback"/></library:library>`,
    ],
    ["Basic/Standard/Playback.xml", module],
  ];
  const manifest = `<?xml version="1.0"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3"><manifest:file-entry manifest:full-path="/" manifest:media-type="${MIME}" manifest:version="1.3"/>${entries
    .slice(1)
    .map(
      ([path]) =>
        `<manifest:file-entry manifest:full-path="${path}" manifest:media-type="text/xml"/>`,
    )
    .join(
      "",
    )}<manifest:file-entry manifest:full-path="Basic/" manifest:media-type="application/vnd.sun.star.basic-library"/><manifest:file-entry manifest:full-path="Basic/Standard/" manifest:media-type="application/vnd.sun.star.basic-library"/></manifest:manifest>`;
  entries.push(["META-INF/manifest.xml", manifest]);
  return zip(entries);
}
export const exportODS = createOds;
