# Optional FFmpeg conversion service

The website can convert browser-supported videos locally. This optional Python
service adds FFmpeg decoding for additional video formats. It produces exactly
the same indexed frame format; it does not itself control LibreOffice.

Requires Python 3.10+ and FFmpeg/ffprobe available on `PATH`.

```sh
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Run these commands from the project root. Windows users can use the equivalent
`.venv\Scripts\python` and `.venv\Scripts\uvicorn` commands.

Visit `http://127.0.0.1:8000/docs` for the interactive API documentation, or check
`GET /health` (`/api/health` is an alias). The service is intentionally separate
from the web frontend so the frontend works without a running Python server.

## Convert a video

```sh
curl -f http://127.0.0.1:8000/api/convert \
  -F file=@clip.mp4 -F width=64 -F fps=8 -F duration=10 \
  -F start=0 -F palette=color -o clip.celluloid.json
```

`POST /api/convert` accepts multipart form fields:

| Field | Default | Supported values |
| --- | --- | --- |
| `file` | Required | Local video file, up to 100 MiB |
| `width` | 64 | Integer, 16–160 cells |
| `fps` | 8 | Integer, 1–15 |
| `duration` | 10 | Seconds, greater than zero and at most 30 |
| `start` | 0 | Seconds, 0–86400, before the end of the clip |
| `palette` | `color` | `color`, `grayscale`, or `mono` |

Frames are capped at 240, so higher frame rates shorten the effective duration.
Height is derived from display aspect ratio, including pixel aspect ratio and
rotation metadata, and capped at 90 cells. Tall videos reduce width to preserve
their shape. Inspect the returned dimensions rather than assuming the requested
width. No audio is returned.

The JSON response is `{version:1,width,height,fps,palette,frames,duration}`. Each
frame is a flat, row-major integer array of palette indices. The color palette
contains 216 web-safe colors, ordered by red, then green, then blue. Grayscale
contains 16 levels; monochrome uses the studio's ink/cream pair (`#171c24`,
`#f8f4e9`), with the lighter color starting at luma 128. Luma uses Rec. 709
weights. Duration equals the returned frame count divided by fps.

The API streams uploads into a temporary file, limits total multipart request
size, rejects empty or undecodable uploads, enforces FFmpeg timeouts, disallows
network protocols in decoders, and removes all temporary files after completion.
Two conversions can run at once; additional requests receive 503. These limits
bound a local prototype's resource use. This is a local service without user
authentication or a persistent job queue; public multi-user deployment needs
authentication, per-user quotas, worker isolation and reverse-proxy limits.

Canceling or closing the browser request does not terminate an FFmpeg conversion
already running on the server. It may finish in the background and release its
slot afterward; ffprobe and FFmpeg have timeouts of 15 and 90 seconds respectively.
Even repeated task cancellation retains the slot and temporary files until the
decoder finishes. Decoder stdout is capped at 1 MiB; stderr retains a 16 KiB tail.
Temporary files are removed when the server-side task completes.

Browser CORS origins default to localhost and 127.0.0.1 on ports 5173, 3000 and
8765 (the native companion's frontend port).
Set `CELLULOID_ORIGINS` to a comma-separated list for another development origin
or deployment. Avoid exposing this API publicly without access controls.

## Tests

```sh
.venv/bin/pip install -r backend/requirements-dev.txt
.venv/bin/python -m pytest backend/tests -q
```

Integration tests generate short videos with FFmpeg and upload them through the
actual HTTP endpoint. They verify all three palette modes, metadata sizing,
validation, limits, invalid files and concurrent slot behavior.
