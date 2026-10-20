"""Bounded, local FFmpeg conversion service for Celluloid indexed frames."""
from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Annotated, Literal

import anyio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import numpy as np

from native.processes import OutputLimitError, run_bounded

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024
MAX_FRAMES = 240
FFMPEG_TIMEOUT = 90


class BodyLimitMiddleware:
    """Bound the whole multipart request, including uploads parsed before routing."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = 0
        if declared > MAX_REQUEST_BYTES:
            response = b'{"detail":"Upload exceeds the 100 MiB limit."}'
            await send({"type": "http.response.start", "status": 413,
                        "headers": [(b"content-type", b"application/json")]})
            return await send({"type": "http.response.body", "body": response})
        consumed = 0

        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            consumed += len(message.get("body", b""))
            if consumed > MAX_REQUEST_BYTES:
                raise HTTPException(413, "Upload exceeds the 100 MiB limit.")
            return message

        await self.app(scope, bounded_receive, send)


app = FastAPI(title="Celluloid conversion API", version="1.0.0")
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv(
        "CELLULOID_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:8765,http://127.0.0.1:8765"
    ).split(",") if origin.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
_slots = asyncio.Semaphore(2)


async def _run_owned_conversion(convert):
    """Retain the caller's slot and files until its decoder thread has finished.

    Cancelling an asyncio task does not stop a Python worker thread. Shield the
    worker and defer cancellation, including repeated cancel() calls, so the
    route's cleanup cannot remove files while FFmpeg still uses them.
    """
    worker = asyncio.create_task(anyio.to_thread.run_sync(convert))
    cancellation = None
    while True:
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError as error:
            if worker.cancelled():
                raise
            if cancellation is None:
                cancellation = error
            continue
        except Exception:
            # Awaiting observes worker failures even when the request was
            # cancelled; cancellation remains the request's final outcome.
            if cancellation is not None:
                raise cancellation
            raise
        if cancellation is not None:
            raise cancellation
        return result


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess:
    try:
        # Never invoke a shell or accept input URLs. The protocol whitelist also
        # prevents an uploaded playlist from making remote network requests.
        return run_bounded(command, timeout)
    except FileNotFoundError as exc:
        raise HTTPException(503, "Install FFmpeg and ffprobe on the API server.") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(422, "Video decoding timed out. Try a shorter or smaller clip.") from exc
    except subprocess.CalledProcessError as exc:
        raise HTTPException(422, "The file could not be decoded as a video.") from exc
    except OutputLimitError as exc:
        raise HTTPException(422, "Video metadata exceeds the supported output limit.") from exc


def _palette(mode: str) -> list[str]:
    if mode == "mono":
        return ["#171c24", "#f8f4e9"]
    if mode == "grayscale":
        return [f"#{i:02x}{i:02x}{i:02x}" for i in range(0, 256, 17)]
    return [f"#{r:02x}{g:02x}{b:02x}" for r in range(0, 256, 51)
            for g in range(0, 256, 51) for b in range(0, 256, 51)]


def convert_video(source: Path, target: Path, width: int, fps: int,
                  duration: float, start: float, palette: str) -> dict:
    probe = _run([
        "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-select_streams", "v:0", "-show_entries",
        "stream=width,height,sample_aspect_ratio:stream_side_data=rotation:stream_tags=rotate:format=duration",
        "-of", "json", str(source),
    ], 15)
    try:
        metadata = json.loads(probe.stdout)
        stream = metadata["streams"][0]
        source_width, source_height = int(stream["width"]), int(stream["height"])
        if not (0 < source_width <= 8192 and 0 < source_height <= 8192
                and source_width * source_height <= 33_554_432):
            raise ValueError("Unsupported source size")
        sar = stream.get("sample_aspect_ratio", "1:1").split(":")
        pixel_ratio = int(sar[0]) / int(sar[1]) if len(sar) == 2 and int(sar[1]) else 1
        display_width, display_height = source_width * pixel_ratio, source_height
        rotation = next((float(s["rotation"]) for s in stream.get("side_data_list", [])
                         if "rotation" in s), float(stream.get("tags", {}).get("rotate", 0)))
        if not math.isfinite(rotation):
            raise ValueError("Invalid rotation")
        if round(rotation) % 180:
            display_width, display_height = display_height, display_width
        if not (math.isfinite(display_width) and display_width > 0):
            raise ValueError("Invalid display dimensions")
        source_duration = float(metadata.get("format", {}).get("duration", "nan"))
    except (ValueError, KeyError, IndexError, TypeError, ZeroDivisionError, OverflowError) as exc:
        raise HTTPException(422, "Video metadata is missing or unsupported.") from exc
    if math.isfinite(source_duration) and start >= source_duration:
        raise HTTPException(422, "Start time must be before the end of the video.")
    aspect = display_height / display_width
    height = max(1, round(width * aspect))
    if height > 90:
        height = 90
        width = max(1, round(height / aspect))
    frame_limit = min(MAX_FRAMES, max(1, math.ceil(duration * fps)))
    effective_duration = min(duration, frame_limit / fps)
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-threads", "2", "-protocol_whitelist", "file,pipe", "-ss", str(start),
        "-i", str(source), "-map", "0:v:0", "-an", "-sn", "-dn",
        "-t", str(effective_duration), "-vf",
        f"fps={fps},scale={width}:{height}:flags=area,setsar=1",
        "-frames:v", str(frame_limit), "-threads", "2", "-f", "rawvideo",
        "-pix_fmt", "rgb24", str(target),
    ], FFMPEG_TIMEOUT)
    frame_bytes = width * height * 3
    size = target.stat().st_size
    if size == 0 or size % frame_bytes or size > frame_limit * frame_bytes:
        raise HTTPException(422, "No complete video frames could be decoded.")
    pixels = np.fromfile(target, dtype=np.uint8).reshape(-1, height * width, 3)
    if palette == "color":
        channels = ((pixels.astype(np.uint16) + 25) // 51)
        indices = channels[:, :, 0] * 36 + channels[:, :, 1] * 6 + channels[:, :, 2]
    else:
        # Match the browser's Rec. 709 luma palette mapping.
        luminance = pixels[:, :, 0] * .2126 + pixels[:, :, 1] * .7152 + pixels[:, :, 2] * .0722
        indices = ((luminance >= 128) if palette == "mono"
                   else np.floor(luminance / 17 + .5))
    frames = indices.astype(np.uint8).tolist()
    return {"version": 1, "width": width, "height": height, "fps": fps,
            "palette": _palette(palette), "frames": frames,
            "duration": len(frames) / fps}


@app.get("/health")
@app.get("/api/health")
async def health():
    available = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    return {"status": "ok" if available else "ffmpeg-missing", "ffmpeg": available,
            "maxUploadBytes": MAX_UPLOAD_BYTES, "maxFrames": MAX_FRAMES}


@app.post("/api/convert")
async def convert(
    file: Annotated[UploadFile, File()],
    width: Annotated[int, Form(ge=16, le=160)] = 64,
    fps: Annotated[int, Form(ge=1, le=15)] = 8,
    duration: Annotated[float, Form(gt=0, le=30, allow_inf_nan=False)] = 10,
    start: Annotated[float, Form(ge=0, le=86400, allow_inf_nan=False)] = 0,
    palette: Annotated[Literal["color", "grayscale", "mono"], Form()] = "color",
):
    try:
        if _slots.locked():
            raise HTTPException(503, "Both conversion slots are busy. Try again shortly.")
        async with _slots:
            with tempfile.TemporaryDirectory(prefix="celluloid-") as directory:
                source, target = Path(directory) / "upload", Path(directory) / "frames.rgb"
                total = 0
                with source.open("wb") as output:
                    while chunk := await file.read(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_UPLOAD_BYTES:
                            raise HTTPException(413, "Upload exceeds the 100 MiB limit.")
                        output.write(chunk)
                if total == 0:
                    raise HTTPException(422, "Choose a nonempty video file.")
                return await _run_owned_conversion(
                    lambda: convert_video(source, target, width, fps, duration, start, palette))
    finally:
        await file.close()
