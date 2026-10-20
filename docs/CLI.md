# The terminal route

The CLI has no web UI, local HTTP server, FastAPI, NumPy or pip dependency. It
uses the Python standard library, FFmpeg/ffprobe for decoding, and LibreOffice's
own UNO binding for rendering. Run commands from the repository root with
Python 3.10 or newer. The protocol and JSON files are shared with the web studio.

## Install the native prerequisites

On Debian/Ubuntu:

```sh
sudo apt install ffmpeg libreoffice-calc python3-uno
/usr/bin/python3 -m native.cli --help
```

Use `/usr/bin/python3` when your distribution installs UNO for the system Python.
A separate venv may not see it. On Windows/macOS, use a Python interpreter with a
UNO binding matching the installed LibreOffice release. Some builds include one;
others need platform-specific setup. `pip install uno` is not the LibreOffice
binding. Windows/macOS native setup and physical devices have not been validated
in this repository's build environment.

Conversion alone needs Python and FFmpeg, with no LibreOffice installation.
Playback and live camera rendering need LibreOffice and Python UNO.

For MacBook installation, the bundled Python check, camera discovery and complete
native commands, follow the [macOS README guide](../README.md#install-and-run-on-a-macbook).

## Convert a video

```sh
python3 -m native.cli convert input.mp4 -o clip.celluloid.json \
  --width 48 --fps 8 --palette grayscale --start 0 --duration 10
```

Import that JSON in the web studio or play it from the CLI. Frames are row-major
palette indices, not images placed over spreadsheet cells. Output is capped at
240 frames and 160 × 90 cells, preserving display aspect ratio. File inputs are
local files up to 100 MiB; clip JSON is limited to 25 MiB. Higher FPS can shorten
the available duration to fit the frame cap. There is no audio.

## Play through actual cells

```sh
python3 -m native.cli play input.mp4 --width 48 --palette grayscale --hold
python3 -m native.cli play clip.celluloid.json --loops 0
```

The default launches a dedicated graphical Calc process and a fresh document.
`--hold` keeps the final frame visible until Ctrl+C. Without `--hold`, an owned
LibreOffice process closes after playback; use `--save final.ods` to retain the
last frame. `--loops 0` repeats until interrupted. JSON playback preserves its
stored grid and palette; video conversion options such as `--width` and
`--palette` apply to video inputs. `--fps` can override JSON playback speed.

The terminal reports rendered frames, skipped frames and render time. Timing
uses a monotonic clock; when Calc is slow, stale frames are skipped. Start with
48 columns and monochrome/grayscale, then measure the result on your computer.

## Stream a live camera

```sh
# Linux / Video4Linux2
python3 -m native.cli webcam --device /dev/video0 --width 48 --palette grayscale

# macOS / AVFoundation: device index 0, no audio device
python3 -m native.cli webcam --device 0:none --mirror

# Windows / DirectShow: use your camera's actual device name
python3 -m native.cli webcam --device "Integrated Camera"
```

Grant OS camera access to your terminal/Python/FFmpeg as appropriate. Camera names
and supported capture modes depend on the device. FFmpeg can list macOS devices
with `ffmpeg -f avfoundation -list_devices true -i ""`, and Windows devices with
`ffmpeg -list_devices true -f dshow -i dummy`. These discovery commands normally
print the device list and exit with an error because no capture was requested.

`--capture-size 640x480` and `--capture-fps 30` configure the camera hardware.
`--fps 8` controls cell update sampling independently. Choose a capture mode
supported by the device. `--input-format` explicitly selects `v4l2`,
`avfoundation`, or `dshow` when automatic OS selection is unsuitable.

Live capture uses a one-frame mailbox. Decoding keeps up with the source while
Calc consumes the newest available frame; there is no unbounded frame queue.
`--duration 10` stops capture after approximately ten seconds. Ctrl+C stops the
decoder, releases its camera handle and cleans up the owned Calc process.

## Existing Calc or a headless job

Use the [companion instructions](../native/README.md) to launch a separate
loopback UNO process. Connect without an HTTP server:

```sh
python3 -m native.cli play clip.celluloid.json \
  --uno-url 'uno:socket,host=127.0.0.1,port=2002;urp;StarOffice.ComponentContext'
```

An externally managed LibreOffice process stays running. The CLI creates its own
document; it does not take over an existing workbook. Keep UNO bound to loopback.

```sh
python3 -m native.cli play input.mp4 --headless --save final.ods
```

Headless mode hides the automatically launched Calc process. `--save` stores the
last rendered frame as a **static** ODS snapshot and overwrites the destination.
For an animated ODS with embedded playback, use the web export. `--headless`
has no effect on an externally managed process and is rejected in that case.

## Verification without Calc

```sh
python3 -m native.cli play clip.celluloid.json --simulate
python3 -m unittest discover -s native -v
```

Simulation is labeled and does not prove native rendering or produce an ODS.
Tests include real FFmpeg conversion and mocked rendering/camera lifecycle.
Actual CLI playback and physical camera behavior still need device acceptance
testing; see [verification](verification.md).
