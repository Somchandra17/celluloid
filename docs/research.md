# Video as spreadsheet cells: architecture research

Research date: 19 October 2026. This document separates facts established by primary documentation from implementation recommendations and unmeasured performance expectations.

## Recommendation

Build one conversion format with two players: a fast browser spreadsheet-style grid for immediate video and webcam feedback, and a LibreOffice Calc player that changes genuine cell backgrounds. The implemented `.ods` exporter contains the first frame as genuine styled cells, a hidden frame-data sheet, and an embedded LibreOffice Basic playback macro. The first frame opens without running code; animation requires explicitly running the included macro under the user's macro policy.

Use the browser's native video decoder and Canvas APIs for interactive previews and live camera sampling. Keep camera frames in the browser by default. Use an FFmpeg-backed upload service when conversion needs to handle formats unsupported by the browser, produce deterministic frames, or create downloadable playback packages. Python is particularly suitable for the companion because LibreOffice exposes its UNO API to Python. A simple HTTP backend can be implemented with FastAPI, whose `UploadFile` support provides streamed/spooled multipart handling. Node with an FFmpeg subprocess is equally reasonable if keeping a TypeScript stack is more valuable; neither needs a full office suite on the server. [FastAPI file handling](https://fastapi.tiangolo.com/tutorial/request-files/)

These recommendations are engineering judgments, not claims that a particular spreadsheet can sustain a given frame rate. Measure actual rendering throughput before promising 15, 24, or 30 FPS in Calc.

## What counts as the real feature

- **Browser preview:** a grid drawn with square colored cells, spreadsheet column labels, row numbers, and optional selection. This is a custom visual spreadsheet surface. It is not LibreOffice running in a tab and is not a full formula editor.
- **Native Calc playback:** a desktop Calc document whose `CellBackColor` properties change repeatedly. This satisfies the original requirement of video playing through actual spreadsheet cells.
- **ODS export:** genuine styled spreadsheet cells representing the first frame, plus stored RGB frame data and an embedded Basic player. It opens in LibreOffice without the companion application. If macros are blocked, it displays the first frame. If the user permits the trusted document macro and runs `PlayVideo`, it attempts playback by updating cell fills. ZIP/XML structure, initial real cell colors, frame storage, and macro packaging have automated checks; those checks alone do not establish that the macro executes or achieves the requested FPS in desktop LibreOffice.
- **Live webcam into Calc:** needs a bridge between the browser's sampled camera frames and a local Calc player. A hosted website cannot simply reach into a user's installed LibreOffice process. The installed companion should establish the connection, or the user can explicitly run a local endpoint. Keep UNO sockets bound to loopback and avoid exposing them as remote application APIs.

## Rendering alternatives

| Approach                   | Relevant capability                                                                            | License / constraints                                                                  | Decision                                                                                                                 |
| -------------------------- | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Custom browser Canvas grid | Precise control over small colored rectangles, frame pacing, overlays, and camera sampling     | Original application code can be permissively licensed; uses browser APIs              | Best first interactive player; state clearly that it is a spreadsheet-style preview                                      |
| LibreOffice Calc + UNO     | Genuine spreadsheet cell backgrounds and desktop document integration                          | LibreOffice uses MPL 2.0 with components under additional open-source licenses         | Best native spreadsheet target; companion installation and measured performance required                                 |
| Glide Data Grid            | Canvas-based React grid, selection, accessibility, custom cell rendering, rapid-update support | MIT                                                                                    | Good upgrade when a richer interactive grid is needed; benchmark full-frame color changes                                |
| Univer                     | Canvas rendering, spreadsheet model, formula engine, extensible office SDK                     | Apache 2.0 core; important Pro capabilities are separately commercial                  | Best candidate if this evolves into a full browser spreadsheet editor; too much machinery for the initial pixel renderer |
| Jspreadsheet CE            | Spreadsheet editing and familiar cell/grid controls                                            | MIT for CE; distinguish CE from Pro and its dependencies                               | Suitable for editing small grids; validate repaint behavior at video rates                                               |
| Handsontable               | Mature spreadsheet-like grid                                                                   | Current license distinguishes commercial use from limited noncommercial/evaluation use | Exclude from an all-permissive-open-source default                                                                       |

The license and advertised capability descriptions above come from the projects' own sources: [LibreOffice licenses](https://www.libreoffice.org/licenses/), [Glide Data Grid repository](https://github.com/glideapps/glide-data-grid), [Univer repository and open-source/Pro comparison](https://github.com/dream-num/univer), [Jspreadsheet CE repository](https://github.com/jspreadsheet/ce), and [Handsontable license](https://github.com/handsontable/handsontable/blob/develop/LICENSE.txt). Performance suitability in the decision column is an inference; no head-to-head benchmark is claimed here.

An office-suite server such as Collabora/LibreOffice Online would add server processes, document sessions, and remote rendering to an operation that can run locally in the browser. It may be useful if collaborative office document editing becomes a requirement; it is not necessary for the video-to-cell pipeline. Building a video player should not initially require forking LibreOffice.

## Browser video and webcam pipeline

1. For a file preview, use an object URL as a `<video>` source. For a webcam, call `navigator.mediaDevices.getUserMedia({video: ..., audio: false})` from a user action and assign the returned stream to the video's `srcObject`.
2. Draw the decoded frame to a tiny sampling canvas whose dimensions equal the requested cell grid, for example 96 × 54. Read its RGBA pixels and optionally quantize them to a reduced palette.
3. Draw each sampled color into its corresponding cell rectangle. Keep spreadsheet labels, selection, and controls independent from the pixel buffer so they do not affect export.
4. Prefer `requestVideoFrameCallback` for processing new decoded video frames, with a throttled `requestAnimationFrame` fallback. The callback API is best-effort and runs on the main thread; avoid promises of strict frame timing.
5. Track source timestamp and measured displayed FPS. On overload, drop stale live frames rather than queueing them and increasing latency.
6. Stop every media track when the user stops the camera or switches input. Treat device denial, no device, and an ignored permission request as normal UI states.

Camera access requires a secure context and browser permission. HTTPS is needed for deployment; localhost is suitable for local development. An embedded site may also need camera permission delegated by its embedding page. [Media capture API](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia), [secure contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Secure_Contexts), [video frame callbacks](https://developer.mozilla.org/en-US/docs/Web/API/HTMLVideoElement/requestVideoFrameCallback)

The output canvas can later be captured with `captureStream()` and passed to a browser recorder if a shareable video of the effect is wanted. That is a separate output from a real spreadsheet document. [Canvas stream capture](https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/captureStream)

## Backend conversion and shared frame format

Use FFprobe to inspect video streams, duration, dimensions, and rotation metadata. Convert only a bounded clip, resizing while preserving aspect ratio and sampling a requested FPS. FFmpeg has documented `fps`, `scale`, and `pad` filters for this work. Decode to RGB bytes rather than writing thousands of temporary PNG files if there is no need to retain intermediate images. [FFmpeg filter reference](https://ffmpeg.org/ffmpeg-filters.html)

A minimal portable format can contain a version number, column/row counts, FPS, frame count, palette mode, timestamps, and frame RGB buffers. The browser player and Calc companion must agree on top-left origin and row-major ordering. Prefer a separate binary or compressed transport for larger clips; JSON integer arrays are acceptable for short demonstrations but expensive.

An uncompressed 96 × 54 RGB frame is 15,552 bytes. Ten seconds at 12 FPS is 1,866,240 bytes before format overhead; 160 × 90 at 24 FPS is 1,036,800 RGB bytes per second. Those arithmetic estimates help choose explicit clip limits; they are not storage benchmarks. Palette indices and compression can reduce payload size.

For a deployed upload backend, bound file size, decoded pixels, output frame count, duration, and subprocess runtime. Use generated temporary names and argument arrays instead of shell commands. Return structured conversion errors and remove temporary uploads on completion or failure. Long-lived deployments should move conversion to a bounded worker queue, with progress/status endpoints and expired-job cleanup. Camera rendering itself should not require continuous server uploads.

FFmpeg is normally LGPL 2.1 or later, with optional GPL parts and other configuration-sensitive restrictions. Record the deployed build configuration and licenses when redistributing a binary or container. A separate subprocess does not eliminate the need to comply with the binary's distribution terms. [FFmpeg legal documentation](https://www.ffmpeg.org/legal.html)

## Native LibreOffice player

The UNO `CellProperties` service explicitly exposes `CellBackColor`; `IsCellBackgroundTransparent` must be false for the color to be used. Set equal physical column width and row height to create square cells. This is a real cell-formatting operation, not an overlaid image. [Cell properties reference](https://api.libreoffice.org/docs/idl/ref/servicecom_1_1sun_1_1star_1_1table_1_1CellProperties.html)

Wrap one frame's updates in `lockControllers()` / `unlockControllers()` with a `finally` block so controller notifications are restored after failure. Do not lock controllers around the entire playback loop, because the user needs to see intermediate frames. The API suspends controller notifications; it does not promise video-grade rendering. [XModel controller locks](https://api.libreoffice.org/docs/idl/ref/interfacecom_1_1sun_1_1star_1_1frame_1_1XModel.html)

`XCellRangeData.setDataArray()` batches cell values, not arbitrary individual background colors. Therefore a statement that this API writes an entire RGB frame's formatting in one call would be incorrect. [Range data API](https://api.libreoffice.org/docs/idl/ref/interfacecom_1_1sun_1_1star_1_1sheet_1_1XCellRangeData.html)

Start with direct fills: skip unchanged cells and combine consecutive same-color cells on each row into range assignments. A 16- or 32-color palette can improve grouping. An alternative experiment is palette indices written with `setDataArray()` plus preconfigured conditional formatting. That shifts work into Calc's conditional-format evaluation and is not established as faster without measurement.

Provide playback speed, pause, stop, and frame stepping. Drive timing from monotonic elapsed time, selecting the appropriate source frame after a slow repaint instead of adding cumulative drift. Report measured display FPS separately from requested FPS. Keep the initial native resolution conservative, such as 48 × 27 or 64 × 36.

## Suggested acceptance checks

- Upload a known short clip, confirm duration and frame count, and compare selected RGB cells with the reference decode.
- Verify a portrait clip keeps its aspect ratio and does not silently stretch.
- Confirm camera start, permission denial, stop, source switching, and device cleanup.
- Confirm browser output changes across timestamps and handles resize without losing playback state.
- Open the generated `.ods` in LibreOffice and inspect actual background properties and grid dimensions.
- Run the native player against at least two frames and read back selected cells through UNO to demonstrate real color changes.
- Exercise corrupt uploads, excessive conversion settings, FFmpeg failure, and cancellation.
- Publish measured results with environment and grid dimensions; do not equate a canvas FPS reading with native Calc throughput.
