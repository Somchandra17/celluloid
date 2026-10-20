# Celluloid: real LibreOffice cell playback

The web app previews video and webcam frames in its own spreadsheet grid. This
optional companion paints **actual LibreOffice Calc cell backgrounds** using UNO.
Each browser-supplied indexed frame becomes grouped cell-range color updates.
It creates a new Calc document and leaves the last displayed frame open so you
can save it as `.ods`. It does not modify an existing document.

For direct video/webcam playback without a web UI or HTTP server, see the
[terminal CLI guide](../docs/CLI.md).

MacBook users: start with the [macOS installation and run guide](../README.md#install-and-run-on-a-macbook),
including the LibreOffice bundled-Python check and explicit app paths.

## Install and run

For automatic prerequisite installation and startup on Linux/macOS/Windows, use
the [one-command setup launcher](../docs/SETUP.md). It serves the bundled studio
through this companion without requiring Node or npm. The commands below are
the manual route.

You need LibreOffice Calc and a Python interpreter that can `import uno`.
On Debian/Ubuntu:

```sh
sudo apt install libreoffice-calc python3-uno
```

The quickest launch automatically starts LibreOffice with a dedicated profile,
then starts the bridge. From the repository root, use:

```sh
/usr/bin/python3 native/bridge.py --launch-lo --web-root dist
```

Open **http://127.0.0.1:8765** and paste the token printed in the terminal into
**Connect LibreOffice**. `dist` is the local static frontend. Run `npm run build` once if you
also want its downloadable source toolkit. No framework compilation is needed. Save any desired workbook before stopping the
companion: `--launch-lo` stops its own LibreOffice process when the bridge exits.
It leaves other LibreOffice processes alone.

If connecting from a separate web-development server instead, use:

```sh
/usr/bin/python3 native/bridge.py --launch-lo --allow-origin http://localhost:5173
```

`--lo-binary /path/to/soffice` overrides executable discovery. `--uno-port 2003`
selects another loopback port. `--headless` is available for integration tests;
normal playback launches a visible Calc window.

For manual process management, start a **separate LibreOffice process/profile**
with its UNO socket bound to loopback. Do not expose port 2002 to your network;
UNO has no pairing-token auth. Keep this process graphical to watch the cells:

```sh
libreoffice '-env:UserInstallation=file:///tmp/celluloid-lo' \
  '--accept=socket,host=127.0.0.1,port=2002;urp;StarOffice.ServiceManager' \
  --norestore --nodefault --nofirststartwizard
```

Then start the companion from the project root. Use `/usr/bin/python3` on Linux
so it can find the distribution's `python3-uno` package:

```sh
/usr/bin/python3 native/bridge.py --allow-origin http://localhost:5173
```

The terminal prints a fresh pairing token. In Celluloid, open **Connect LibreOffice**,
enter `http://127.0.0.1:8765` and paste that token. Choose a file or webcam and
start playback. Closing the companion invalidates its generated token.

For a stable token across launches, use `--token-file ~/.config/celluloid/token`.
New token files are created with owner-only permissions. Keep the token private;
it authorizes creation of Calc documents and cell updates through this bridge.
The browser keeps the pairing token in memory rather than adding it to URLs.

On Windows/macOS the interpreter and pyuno setup varies by LibreOffice build;
use an interpreter supplied or configured with that installation's UNO module.
This project does not bundle LibreOffice or claim platform-wide native support.

## Recommended local web mode

Browsers can block a hosted HTTPS site from accessing local HTTP services due to
mixed-content or local-network policies, even when CORS is correctly configured.
The reliable fallback is to serve the built frontend through the companion:

```sh
/usr/bin/python3 native/bridge.py --launch-lo --web-root dist
```

Open **http://127.0.0.1:8765** and pair with the printed token. This keeps the
web page and bridge on the same origin. Webcam permissions require a secure
context; browsers generally treat loopback localhost as trustworthy. A browser
may still request camera or local-network permission.

To allow a hosted site, specify its exact origin with no trailing slash:

```sh
/usr/bin/python3 native/bridge.py --allow-origin https://your-celluloid.example
```

Origins can be repeated. Wildcards and the opaque `null` origin are not accepted.
The bridge answers private-network CORS preflights but cannot bypass browser
policies. HTTP is bound only to `127.0.0.1`; Host validation also guards DNS
rebinding. All API calls require `Authorization: Bearer <token>`.

## Protocol

Every JSON write uses `Content-Type: application/json`. A single request must
finish before sending the next frame; drop intermediate source frames instead
of queueing them. This provides backpressure for slower Calc rendering.

| Method/path       | Request                                            | Response                                                                 |
| ----------------- | -------------------------------------------------- | ------------------------------------------------------------------------ |
| `GET /health`     | None                                               | `{ok, protocol: "cell-video-v1", mode, maxWidth, maxHeight, maxPalette}` |
| `POST /session`   | `{width, height, palette: ["#000000", "#ffffff"]}` | `{sessionId, width, height, mode}`                                       |
| `POST /frame`     | `{sessionId, sequence: 0, pixels: [0, 1, ...]}`    | `{sequence, changedCells, rangeWrites, renderMs}`                        |
| `DELETE /session` | `{sessionId}`                                      | `{stopped: true}`                                                        |

Pixels are row-major palette indices. Maximum grid is 256 columns × 144 rows;
palette size is 1–256; request limit is 2 MB. Sequence numbers must increase
within a session. A stale sequence or unknown session returns HTTP 409. Creating
a new session creates a fresh Calc document. Deleting a session stops updates;
the final document stays visible. Pause by simply not sending frames.

Color writes are grouped into adjacent runs within each row, and cells whose
palette indices have not changed are skipped. Controllers are locked around
each frame and always unlocked in `finally`. A failed partial write forces a
full redraw on the next frame. High-resolution full-color footage may be slow;
start with 48 × 27 cells and a small palette and measure the returned `renderMs`.
Audio is not synchronized to Calc playback.

## Tests and simulation

```sh
python3 -m unittest discover -s native -v
python3 native/bridge.py --simulate --allow-origin http://localhost:5173
```

Simulation exercises the real HTTP protocol and the same frame-diff/run grouping
code without LibreOffice. `/health` explicitly returns `mode: "simulation"`.
It does **not** prove that a native LibreOffice installation works or produce a
real Calc window. The unit suite covers authentication, origins, preflight,
frame validation, stale-frame rejection, changed-run rendering, partial-failure
recovery, and a complete HTTP session/frame/stop exchange.

The opt-in `test_native_integration.py` creates its own document in an already
running isolated LibreOffice process. Set `CELLULOID_TEST_UNO_URL` to enable it:

```sh
CELLULOID_TEST_UNO_URL='uno:socket,host=127.0.0.1,port=2002;urp;StarOffice.ComponentContext' \
  /usr/bin/python3 -m unittest discover -s native -v
```

Validation in the build environment: 50 native/CLI/process checks pass; two
real-UNO checks are opt-in. The real model-only test passed separately: two
frames produced exact cell-color readbacks, an unchanged frame wrote no ranges,
and controller updates were unlocked. It uses an actual Calc document model
without the desktop factory/view loader. This establishes the renderer's cell
updates, not full desktop or CLI playback.

The bundled LibreOfficeDev 26.8 alpha exceeds the cloud memory budget inside
desktop document creation, before grid setup. A separately extracted runtime
also failed document initialization. Full native playback and exported Basic
macro execution are therefore **not fully validated here**.

For a repeatable desktop/CLI acceptance run on a matched installation:

```sh
/usr/bin/python3 scripts/check-native.py --output /tmp/celluloid-final.ods
```

Choose a new output path. This starts an isolated headless office, runs both real
cell-readback tests, plays a known clip through the actual CLI, saves a static
ODS, reopens it and verifies the final cell colors. It stops its owned office
in cleanup. The **Real LibreOffice acceptance (manual)** GitHub Actions workflow
runs this command with distribution-matched Calc and Python UNO; its first
account-side run is still pending. Neither this command nor the unit suite
tests physical cameras, graphical playback speed, or embedded Basic execution.
Browser playback and bridge simulation do not depend on the native runtime.

No pip dependencies are required. `bridge.py` is standalone and can be copied
to a local machine with LibreOffice plus pyuno installed.
