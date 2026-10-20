# One repository, three execution paths

```text
Video file / webcam
        │
        ├─ Browser media APIs → resize + palette → v1 indexed frames
        │                                      ├─ Canvas studio
        │                                      ├─ animated ODS writer
        │                                      └─ local HTTP companion → UNO → Calc
        │
        └─ CLI / optional FFmpeg API → resize + palette → same v1 frames
                                                       └─ direct UNO → Calc
```

## Ownership and deployment

| Area                                           | Role                                                            | Runs where                                  |
| ---------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------- |
| `dist/`                                        | Dependency-free static studio, media processing and ODS writer  | Browser; a static host may serve its files  |
| `native/cli.py`                                | Convert, play or stream camera with terminal controls           | User's computer, no web server              |
| `native/bridge.py`                             | Authenticated loopback frames and optional local static hosting | User's computer                             |
| `backend/`                                     | Optional FastAPI multipart conversion using FFmpeg              | Local machine or separately managed service |
| `scripts/`                                     | Node-only build, portable archive and release validation        | Developer machine or CI                     |
| `tests/`, `native/test_*.py`, `backend/tests/` | Core, DOM, protocol, CLI, ODS and FFmpeg checks                 | Developer machine or CI                     |

The browser studio and CLI can each run independently. Neither requires the
original preview host or a cloud gateway. The optional API is a decoding
convenience; the native companion is the bridge needed for desktop access from
a browser. CLI playback invokes UNO directly and never passes through HTTP.

## Frame contract

```json
{
  "version": 1,
  "width": 2,
  "height": 1,
  "fps": 8,
  "palette": ["#000000", "#ffffff"],
  "frames": [
    [0, 1],
    [1, 0]
  ],
  "duration": 0.25
}
```

Pixels are row-major palette indices. Files have 1–240 frames, 1–256 colors,
and grids up to 160 × 90 cells. Display aspect ratio is preserved. A clip may
optionally carry a title. The studio accepts the same JSON the CLI/API produce.
The native HTTP transport sends one indexed frame per request with monotonically
increasing sequence numbers. Live streams are not limited to 240 frames because
they retain only the current/most recent frame rather than a full clip.

## Playback and backpressure

Browser playback uses elapsed time rather than accumulating fixed-delay sleeps.
Conversion samples a small canvas; the visible grid is independent from pixel
data. Native rendering groups adjacent changed colors into row ranges and skips
unchanged cells. Controller locks apply to one frame and are always released.

The browser keeps only its most recent pending native frame. The CLI's live
camera path uses a one-frame mailbox between decoding and rendering. Neither
queues an unlimited stream when Calc is slow. Requested FPS is not a native
speed guarantee; render time and skipped frames are reported.

## ODS and trust boundary

Animated ODS stores actual first-frame cell backgrounds, hidden RGB frame data,
and an inspectable Basic module. The document does not fetch remote resources.
Macros must be permitted according to the user's document policy. ODS animation
is limited to 96 × 54 cells and 240 frames; large browser grids are scaled for
export. CLI `--save` is a different output: a static final-frame Calc snapshot.

The companion binds to loopback, validates origins/Host, and requires a bearer
pairing token. UNO itself has no equivalent token authentication and stays on
loopback. A dedicated Calc process/profile avoids taking over open workbooks.

## What remains a local acceptance test

Normal installed LibreOffice/Python UNO, real camera permissions and hardware,
and sustained native frame rates need device testing. Unit simulation and
structurally valid ODS files are not a substitute. See [verification](verification.md).
