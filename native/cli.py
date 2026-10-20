#!/usr/bin/env python3
"""Convert videos and stream video/webcam pixels into real LibreOffice cells.

The CLI uses Python's standard library, FFmpeg, and LibreOffice's own UNO binding.
There is no browser, HTTP bridge, FastAPI, NumPy, or pip dependency in this path.
Run ``python3 -m native.cli --help`` from the repository root.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time

if __package__:
    from .bridge import CalcRenderer, Engine, RequestError, SimulatedRenderer, launch_renderer
    from .processes import OutputLimitError, run_bounded
else:
    from bridge import CalcRenderer, Engine, RequestError, SimulatedRenderer, launch_renderer
    from processes import OutputLimitError, run_bounded


MAX_FRAMES = 240
MAX_WIDTH = 160
MAX_HEIGHT = 90
MAX_VIDEO_BYTES = 100 * 1024 * 1024
MAX_JSON_BYTES = 25 * 1024 * 1024


class CLIError(Exception):
    """An actionable user-facing failure, printed without a Python traceback."""


def finite_number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise CLIError(f"{name} must be between {low} and {high}.")
    return value


def make_palette(mode):
    if mode == "mono":
        return ["#171c24", "#f8f4e9"]
    if mode == "grayscale":
        return [f"#{i:02x}{i:02x}{i:02x}" for i in range(0, 256, 17)]
    if mode != "color":
        raise CLIError("Palette must be color, grayscale, or mono.")
    return [f"#{r:02x}{g:02x}{b:02x}" for r in range(0, 256, 51)
            for g in range(0, 256, 51) for b in range(0, 256, 51)]


def quantize_rgb(raw, mode):
    """Use the browser's Rec. 709 luma and 6×6×6 indexed color mapping."""
    if len(raw) % 3:
        raise CLIError("FFmpeg returned an incomplete RGB pixel.")
    pixels = []
    for offset in range(0, len(raw), 3):
        r, g, b = raw[offset:offset + 3]
        if mode == "color":
            pixels.append(((r + 25) // 51) * 36 + ((g + 25) // 51) * 6 + (b + 25) // 51)
        else:
            luminance = r * .2126 + g * .7152 + b * .0722
            pixels.append(int(luminance >= 128) if mode == "mono" else math.floor(luminance / 17 + .5))
    return pixels


def validate_clip(clip):
    if not isinstance(clip, dict) or type(clip.get("version")) is not int or clip["version"] != 1:
        raise CLIError("Expected a Celluloid version 1 JSON clip.")
    for key, limit in (("width", MAX_WIDTH), ("height", MAX_HEIGHT)):
        if type(clip.get(key)) is not int or not 1 <= clip[key] <= limit:
            raise CLIError(f"Clip {key} must be an integer between 1 and {limit}.")
    finite_number(clip.get("fps"), "Clip fps", 1, 30)
    palette = clip.get("palette")
    if not isinstance(palette, list) or not 1 <= len(palette) <= 256 or any(
        not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color) for color in palette
    ):
        raise CLIError("Clip palette must have 1–256 #RRGGBB colors.")
    frames = clip.get("frames")
    if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_FRAMES:
        raise CLIError("Clip must have between 1 and 240 frames.")
    count = clip["width"] * clip["height"]
    for frame in frames:
        if not isinstance(frame, list) or len(frame) != count or any(
            type(index) is not int or not 0 <= index < len(palette) for index in frame
        ):
            raise CLIError("Each frame must contain one valid integer palette index per cell.")
    return clip


def require_file(path, maximum, label):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise CLIError(f"{label} is not a regular local file: {path}")
    size = path.stat().st_size
    if not 0 < size <= maximum:
        raise CLIError(f"{label} must be nonempty and at most {maximum // (1024 * 1024)} MiB.")
    return path


def load_clip(path):
    path = require_file(path, MAX_JSON_BYTES, "JSON clip")
    try:
        return validate_clip(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise CLIError("Could not read a valid UTF-8 JSON clip.") from error


def run_command(command, timeout):
    try:
        return run_bounded(command, timeout)
    except FileNotFoundError as error:
        raise CLIError(f"Cannot find {command[0]}. Install FFmpeg (including ffprobe).") from error
    except subprocess.TimeoutExpired as error:
        raise CLIError("Video decoding timed out; try a shorter or smaller file.") from error
    except OutputLimitError as error:
        raise CLIError("Decoder output exceeded the supported metadata limit; try another clip.") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()[-1200:] if error.stderr else ""
        raise CLIError("FFmpeg could not decode the input." + (f"\n{detail}" if detail else "")) from error


def dimensions(width, source_width, source_height):
    aspect = source_height / source_width
    height = max(1, math.floor(width * aspect + .5))
    if height > MAX_HEIGHT:
        height = MAX_HEIGHT
        width = max(1, math.floor(height / aspect + .5))
    return width, height


def probe_video(source, ffprobe="ffprobe"):
    result = run_command([
        ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,sample_aspect_ratio:stream_side_data=rotation:stream_tags=rotate:format=duration",
        "-of", "json", str(source),
    ], 15)
    try:
        metadata = json.loads(result.stdout)
        stream = metadata["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        if not (0 < width <= 8192 and 0 < height <= 8192 and width * height <= 33_554_432):
            raise ValueError("Unsupported source size")
        ratio = stream.get("sample_aspect_ratio", "1:1").split(":")
        pixel_ratio = int(ratio[0]) / int(ratio[1]) if len(ratio) == 2 and int(ratio[1]) else 1
        width *= pixel_ratio
        rotation = next((float(item["rotation"]) for item in stream.get("side_data_list", [])
                         if "rotation" in item), float(stream.get("tags", {}).get("rotate", 0)))
        if not math.isfinite(rotation):
            raise ValueError("Invalid rotation")
        if round(rotation) % 180:
            width, height = height, width
        if not all(math.isfinite(value) and value > 0 for value in (width, height)):
            raise ValueError("Invalid aspect ratio")
        duration = float(metadata.get("format", {}).get("duration", "nan"))
        return width, height, duration
    except (ValueError, KeyError, IndexError, TypeError, ZeroDivisionError, OverflowError) as error:
        raise CLIError("Video dimensions or metadata are missing or unsupported.") from error


def convert_video(source, width=48, fps=8, duration=10, start=0, palette="grayscale",
                  ffmpeg="ffmpeg", ffprobe="ffprobe"):
    """Decode bounded local footage without loading the HTTP backend or NumPy."""
    source = require_file(source, MAX_VIDEO_BYTES, "Video")
    if type(width) is not int or not 1 <= width <= MAX_WIDTH:
        raise CLIError("Width must be an integer between 1 and 160.")
    finite_number(fps, "Conversion fps", 1, 15)
    finite_number(duration, "Duration", .001, 30)
    finite_number(start, "Start", 0, 86400)
    colors = make_palette(palette)
    source_width, source_height, source_duration = probe_video(source, ffprobe)
    if math.isfinite(source_duration) and start >= source_duration:
        raise CLIError("Start time must be before the end of the video.")
    width, height = dimensions(width, source_width, source_height)
    frame_limit = min(MAX_FRAMES, max(1, math.ceil(duration * fps)))
    with tempfile.TemporaryDirectory(prefix="celluloid-cli-") as directory:
        target = Path(directory) / "frames.rgb"
        run_command([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-threads", "2",
            "-protocol_whitelist", "file,pipe", "-ss", str(start), "-i", str(source),
            "-map", "0:v:0", "-an", "-sn", "-dn", "-t", str(min(duration, frame_limit / fps)),
            "-vf", f"fps={fps},scale={width}:{height}:flags=area,setsar=1",
            "-frames:v", str(frame_limit), "-threads", "2", "-f", "rawvideo", "-pix_fmt", "rgb24", str(target),
        ], 90)
        frame_bytes = width * height * 3
        size = target.stat().st_size
        if not size or size % frame_bytes or size > frame_limit * frame_bytes:
            raise CLIError("No complete video frames could be decoded.")
        frames = []
        with target.open("rb") as handle:
            while raw := handle.read(frame_bytes):
                frames.append(quantize_rgb(raw, palette))
    return {"version": 1, "width": width, "height": height, "fps": fps,
            "palette": colors, "frames": frames, "duration": len(frames) / fps,
            "title": source.name}


@dataclass
class PlaybackStats:
    rendered: int = 0
    skipped: int = 0
    max_render_ms: float = 0

    def note(self, result):
        self.rendered += 1
        self.max_render_ms = max(self.max_render_ms, result["renderMs"])

    def message(self):
        return (f"{self.rendered} frames rendered; {self.skipped} source frames skipped; "
                f"slowest Calc update {self.max_render_ms:.1f} ms.")


def play_clip(engine, clip, loops=1, fps=None, *, stats=None, clock=time.monotonic,
              sleep=time.sleep, report=None):
    """Use a monotonic timeline and skip overdue source frames instead of queueing."""
    stats = stats if stats is not None else PlaybackStats()
    fps = fps or clip["fps"]
    session = engine.start(clip)
    frames = clip["frames"]
    total = len(frames) * loops if loops else None
    started = clock()
    previous = -1
    last_report = started
    try:
        while True:
            due = max(previous + 1, math.floor((clock() - started) * fps))
            if total is not None:
                due = min(due, total - 1)
            delay = started + due / fps - clock()
            if delay > 0:
                sleep(delay)
            # Recalculate after sleeping: scheduler delays must also drop frames.
            due = max(due, math.floor((clock() - started) * fps))
            if total is not None:
                due = min(due, total - 1)
            stats.skipped += due - previous - 1
            result = engine.frame({"sessionId": session["sessionId"], "sequence": due,
                                   "pixels": frames[due % len(frames)]})
            stats.note(result)
            previous = due
            if report and clock() - last_report >= 1:
                report(stats.message())
                last_report = clock()
            if total is not None and due == total - 1:
                # The final frame owns its full interval too. Otherwise an
                # automatically launched Calc closes one frame too early.
                remaining = started + total / fps - clock()
                if remaining > 0:
                    sleep(remaining)
                break
    finally:
        engine.end({"sessionId": session["sessionId"]})
    return stats


class LatestFrame:
    """One-slot mailbox: a slow Calc render cannot create a growing frame queue."""

    def __init__(self):
        self.condition = threading.Condition()
        self.latest = None
        self.done = False
        self.error = None

    def put(self, sequence, frame):
        with self.condition:
            self.latest = (sequence, frame)
            self.condition.notify_all()

    def finish(self, error=None):
        with self.condition:
            self.done, self.error = True, error
            self.condition.notify_all()

    def get_after(self, sequence, timeout=.25):
        with self.condition:
            self.condition.wait_for(lambda: self.done or self.latest is not None and self.latest[0] > sequence,
                                    timeout=timeout)
            if self.latest is not None and self.latest[0] > sequence:
                return self.latest
            return None


def read_camera_frames(stream, frame_bytes, mailbox):
    sequence = 0
    try:
        while True:
            chunks = bytearray()
            while len(chunks) < frame_bytes:
                chunk = stream.read(frame_bytes - len(chunks))
                if not chunk:
                    if chunks:
                        raise CLIError("Camera decoder returned an incomplete frame.")
                    mailbox.finish()
                    return
                chunks.extend(chunk)
            mailbox.put(sequence, bytes(chunks))
            sequence += 1
    except (OSError, ValueError, CLIError) as error:
        mailbox.finish(error)


def camera_format(requested, platform=None):
    if requested != "auto":
        return requested
    platform = platform or sys.platform
    if platform.startswith("linux"):
        return "v4l2"
    if platform == "darwin":
        return "avfoundation"
    if platform == "win32":
        return "dshow"
    raise CLIError("Choose --input-format v4l2, avfoundation, or dshow for this platform.")


def capture_dimensions(value):
    match = re.fullmatch(r"([1-9][0-9]{0,3})x([1-9][0-9]{0,3})", value)
    if not match:
        raise argparse.ArgumentTypeError("Capture size must use WIDTHxHEIGHT, for example 640x480.")
    width, height = map(int, match.groups())
    if width > 8192 or height > 8192 or width * height > 33_554_432:
        raise argparse.ArgumentTypeError("Capture size is too large (maximum 8192 per side, 32 megapixels).")
    return value


def camera_command(args, width, height):
    input_format = camera_format(args.input_format)
    device = args.device
    if input_format == "dshow" and not device.startswith("video="):
        device = "video=" + device
    filters = f"fps={args.fps},scale={width}:{height}:flags=area,setsar=1"
    if args.mirror:
        filters += ",hflip"
    return [args.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-threads", "2",
            "-f", input_format, "-framerate", str(args.capture_fps), "-video_size", args.capture_size,
            "-i", device, "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", filters,
            "-threads", "2", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]


def stop_decoder(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def stream_camera(engine, args, *, stats=None, report=None):
    stats = stats if stats is not None else PlaybackStats()
    capture_width, capture_height = map(int, args.capture_size.split("x"))
    width, height = dimensions(args.width, capture_width, capture_height)
    palette = make_palette(args.palette)
    session = engine.start({"width": width, "height": height, "palette": palette})
    mailbox = LatestFrame()
    process = None
    reader = None
    try:
        with tempfile.TemporaryFile() as errors:
            try:
                process = subprocess.Popen(camera_command(args, width, height), stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=errors, bufsize=width * height * 3)
            except FileNotFoundError as error:
                raise CLIError("Cannot find FFmpeg; install it before streaming a camera.") from error
            reader = threading.Thread(target=read_camera_frames, args=(process.stdout, width * height * 3, mailbox),
                                      daemon=True, name="celluloid-camera")
            reader.start()
            started = last_report = time.monotonic()
            last_sequence = -1
            try:
                while args.duration is None or time.monotonic() - started < args.duration:
                    frame = mailbox.get_after(last_sequence)
                    if frame is None:
                        if mailbox.done:
                            if mailbox.error:
                                raise CLIError(str(mailbox.error))
                            process.wait(timeout=3)
                            if process.returncode:
                                errors.seek(0, 2)
                                size = errors.tell()
                                errors.seek(max(0, size - 1600))
                                detail = errors.read().decode("utf-8", errors="replace").strip()
                                raise CLIError("Camera capture failed. Check --device, --capture-size, permissions, and device availability."
                                               + (f"\n{detail}" if detail else ""))
                            if not stats.rendered:
                                raise CLIError("Camera capture ended without a frame.")
                            break
                        continue
                    sequence, raw = frame
                    stats.skipped += sequence - last_sequence - 1
                    stats.note(engine.frame({"sessionId": session["sessionId"], "sequence": sequence,
                                             "pixels": quantize_rgb(raw, args.palette)}))
                    last_sequence = sequence
                    if report and time.monotonic() - last_report >= 1:
                        report(stats.message())
                        last_report = time.monotonic()
                if not stats.rendered:
                    raise CLIError("No camera frames arrived before capture stopped. Try a longer --duration or check the device settings.")
            finally:
                stop_decoder(process)
                reader.join(timeout=3)
                process.stdout.close()
    finally:
        # Never leave the camera device or decoder running after Ctrl+C/error.
        if process is not None:
            stop_decoder(process)
            if reader is not None and reader.is_alive():
                reader.join(timeout=3)
            if process.stdout is not None and not process.stdout.closed:
                process.stdout.close()
        engine.end({"sessionId": session["sessionId"]})
    return stats


def save_snapshot(renderer, path):
    if getattr(renderer, "document", None) is None:
        raise CLIError("No actual Calc document is available to save.")
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() != ".ods":
        raise CLIError("--save must end in .ods; it stores the final cell frame, without animation macros.")
    if not path.parent.is_dir():
        raise CLIError(f"Snapshot directory does not exist: {path.parent}")
    import uno
    filter_property = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
    filter_property.Name, filter_property.Value = "FilterName", "calc8"
    overwrite = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
    overwrite.Name, overwrite.Value = "Overwrite", True
    renderer.document.storeAsURL(path.as_uri(), (filter_property, overwrite))
    return path


def positive_integer(value):
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected an integer.") from error
    if result < 1:
        raise argparse.ArgumentTypeError("Expected a positive integer.")
    return result


def add_conversion_options(parser, *, webcam=False):
    parser.add_argument("--width", type=positive_integer, default=48, help="Grid columns, 1–160 (default: 48)")
    parser.add_argument("--fps", type=float, default=8 if webcam else None,
                        help="Target fps, 1–15 for video conversion; JSON playback defaults to its stored fps")
    parser.add_argument("--palette", choices=("color", "grayscale", "mono"), default="grayscale")
    parser.add_argument("--duration", type=float, default=None if webcam else 10,
                        help="Seconds to capture/convert (webcam: until Ctrl+C; video: default 10, max 30)")
    if not webcam:
        parser.add_argument("--start", type=float, default=0, help="Video start offset in seconds")
        parser.add_argument("--ffprobe", default="ffprobe", help="ffprobe executable")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg executable")


def add_calc_options(parser):
    connection = parser.add_mutually_exclusive_group()
    connection.add_argument("--uno-url", help="Connect to an existing local LibreOffice UNO process instead of launching one")
    connection.add_argument("--launch-lo", action="store_true", help="Launch dedicated LibreOffice (the default)")
    connection.add_argument("--simulate", action="store_true", help="Verify the pipeline in memory; does not open real Calc")
    parser.add_argument("--lo-binary", help="Path to libreoffice/soffice executable")
    parser.add_argument("--uno-port", type=positive_integer, default=2002, help="Loopback UNO port for automatic launch (default: 2002)")
    parser.add_argument("--headless", action="store_true", help="Hide launched Calc; useful with --save in scripted processing")
    parser.add_argument("--save", type=Path, help="Save final cell frame as an ODS snapshot; overwrites the path")
    parser.add_argument("--hold", action="store_true", help="Keep final Calc frame visible until Ctrl+C before cleanup")


def make_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    convert = commands.add_parser("convert", help="Convert a local video into browser-compatible indexed JSON")
    convert.add_argument("input", type=Path)
    convert.add_argument("-o", "--output", type=Path, required=True, help="Output .json file (overwrites the path)")
    add_conversion_options(convert)
    play = commands.add_parser("play", help="Play a JSON clip or a local video through actual Calc cell colors")
    play.add_argument("input", type=Path)
    play.add_argument("--loops", type=int, default=1, help="Number of playthroughs; 0 repeats until Ctrl+C")
    add_conversion_options(play)
    add_calc_options(play)
    webcam = commands.add_parser("webcam", help="Stream a camera directly into Calc without a browser")
    webcam.add_argument("--device", required=True,
                        help='FFmpeg device: Linux /dev/video0; macOS 0:none; Windows "Integrated Camera"')
    webcam.add_argument("--input-format", choices=("auto", "v4l2", "avfoundation", "dshow"), default="auto")
    webcam.add_argument("--capture-size", type=capture_dimensions, default="640x480",
                        help="Camera capture size/aspect ratio (default: 640x480); must be supported by the device")
    webcam.add_argument("--capture-fps", type=float, default=30,
                        help="Hardware camera frame rate, 1–120 (default: 30); independent of the cell update --fps")
    webcam.add_argument("--mirror", action="store_true", help="Mirror the live feed horizontally")
    add_conversion_options(webcam, webcam=True)
    add_calc_options(webcam)
    return parser


def main(argv=None):
    parser = make_parser()
    args = parser.parse_args(argv)
    owned = None
    stats = PlaybackStats()
    renderer = None
    interrupted = False
    try:
        if args.width > MAX_WIDTH:
            raise CLIError("--width must be between 1 and 160.")
        if args.fps is not None:
            finite_number(args.fps, "--fps", 1, 15 if args.command != "play" or args.input.suffix.lower() != ".json" else 30)
        if args.command == "webcam":
            finite_number(args.capture_fps, "--capture-fps", 1, 120)
            if args.duration is not None:
                finite_number(args.duration, "--duration", .001, 86400)
            camera_format(args.input_format)
        elif args.command == "convert" or args.input.suffix.lower() != ".json":
            finite_number(args.duration, "--duration", .001, 30)
            finite_number(args.start, "--start", 0, 86400)
        if args.command == "convert":
            clip = convert_video(args.input, args.width, args.fps or 8, args.duration, args.start,
                                 args.palette, args.ffmpeg, args.ffprobe)
            args.output.write_text(json.dumps(clip, separators=(",", ":")) + "\n", encoding="utf-8")
            print(f"Wrote {len(clip['frames'])} frames, {clip['width']} × {clip['height']} cells, "
                  f"{clip['fps']:g} fps to {args.output}.")
            return 0
        if not 1 <= args.uno_port <= 65535:
            raise CLIError("--uno-port must be between 1 and 65535.")
        if args.simulate and args.save:
            raise CLIError("--save requires actual LibreOffice; simulation has no ODS document.")
        if args.headless and (args.uno_url or args.simulate):
            raise CLIError("--headless applies only when launching LibreOffice.")
        if args.save and (args.save.suffix.lower() != ".ods" or not args.save.expanduser().resolve().parent.is_dir()):
            raise CLIError("--save must name an .ods file inside an existing directory.")
        if args.command == "play":
            if args.loops < 0:
                raise CLIError("--loops must be 0 (repeat indefinitely) or a positive integer.")
            clip = load_clip(args.input) if args.input.suffix.lower() == ".json" else convert_video(
                args.input, args.width, args.fps or 8, args.duration, args.start, args.palette, args.ffmpeg, args.ffprobe)
        if args.simulate:
            renderer = SimulatedRenderer()
        elif args.uno_url:
            renderer = CalcRenderer(args.uno_url)
        else:
            renderer, owned = launch_renderer(args.lo_binary, args.uno_port, args.headless)
        print(f"Celluloid {args.command} → {renderer.mode}. Press Ctrl+C to stop.", file=sys.stderr)
        engine = Engine(renderer)
        try:
            report = lambda message: print(message, file=sys.stderr, flush=True)
            if args.command == "play":
                play_clip(engine, clip, args.loops, args.fps, stats=stats, report=report)
            else:
                stream_camera(engine, args, stats=stats, report=report)
            if args.hold:
                print("Holding the final frame. Press Ctrl+C to finish.", file=sys.stderr)
                while True:
                    time.sleep(.5)
        except KeyboardInterrupt:
            interrupted = True
        finally:
            if args.save and stats.rendered:
                output = save_snapshot(renderer, args.save)
                print(f"Saved final cell frame (static ODS snapshot): {output}", file=sys.stderr)
        print(stats.message(), file=sys.stderr)
        return 130 if interrupted else 0
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 130
    except (CLIError, RequestError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"celluloid: {error}", file=sys.stderr)
        return 1
    finally:
        if owned:
            owned.close()


if __name__ == "__main__":
    raise SystemExit(main())
