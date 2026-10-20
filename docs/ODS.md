# Celluloid OpenDocument export

`createOds({ width, height, fps, palette, frames, title? })` returns a browser `Blob` with the `application/vnd.oasis.opendocument.spreadsheet` media type. `exportODS` is an alias. Each frame is an array or `Uint8Array` of `width × height` palette indices; the palette contains up to 256 `#rrggbb` colors. Export supports up to 96 columns, 54 rows, 240 frames and 1–30 requested frames per second.

```js
import { createOds } from "./dist/ods.js";
const blob = createOds({
  width: 2,
  height: 2,
  fps: 5,
  palette: ["#101010", "#ff7040"],
  frames: [new Uint8Array([0, 1, 1, 0]), new Uint8Array([1, 0, 0, 1])],
});
```

The first frame uses genuine spreadsheet cell background colors and opens without running any macro. The document includes `Video` and `Instructions` sheets plus a hidden `_Frames` sheet containing each frame as RGB hex text split into small cells. It embeds a readable LibreOffice Basic module at `Basic/Standard/Playback.xml`.

To animate in desktop LibreOffice, review the embedded code and trust the document according to your own macro policy. Run **Tools → Macros → Run Macro → this document → Standard → Playback → PlayVideo**. Do not lower global macro security. Playback is never automatic. It plays the clip once and leaves the last frame visible. Run `StopVideo` to request stopping, or use LibreOffice's macro interruption controls. `Wait` between frames allows UI repainting; actual frame rate depends on hardware and Calc formatting performance. The macro groups horizontal cells with identical colors and batches controller repaints, but it does not guarantee the requested FPS.

Browser playback and webcam capture do not depend on this macro. A saved ODS represents a recorded clip; streaming live webcam colors into a running Calc document uses the optional local bridge. Export contains no audio, embedded images, external references or network calls. Other ODS viewers can display the static first frame but may not execute LibreOffice Basic.

The dependency-free ZIP writer stores all entries without compression. This makes the format easy to inspect and ensures the required first `mimetype` entry is uncompressed; longer exports can be relatively large. Export limits intentionally bound memory and document size.

Run checks with:

```sh
python tests/test_ods.py
python tests/test_ods.py --libreoffice
```

The first command verifies ZIP CRCs, XML parsing, actual cell color styles, embedded macro packaging, RGB frame round trips, chunk boundaries and invalid input handling. The second also opens and renders an exported ODS to PDF using headless LibreOffice. These checks do not themselves prove Basic macro execution; that requires an environment permitting document macro execution.
