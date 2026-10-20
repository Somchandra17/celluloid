# Local setup launcher

The shared `setup_celluloid.py` engine installs missing prerequisites and runs
the existing bridge with `dist/` as its local web app. It uses the Python standard
library. The shell/Windows launchers bootstrap Python when necessary; application
setup is maintained in one place.

## Start

Extract the whole source archive first; running a script detached from `native/`
and `dist/` is not supported. Open a terminal in that folder:

```text
Linux / macOS:  bash setup.sh
Windows:        .\setup.cmd
```

On macOS, install [Homebrew](https://brew.sh/) and follow its shell setup first.
On Windows 10/11, use [App Installer / WinGet](https://learn.microsoft.com/en-us/windows/package-manager/winget/).
The launcher does not install a new package manager, change global PowerShell
execution policy, or download and execute a remote bootstrap script.

When Python 3.10+ is missing, the platform launcher installs it using the package
manager. The shared engine then:

1. Finds an existing LibreOffice executable and tests candidate Python runtimes
   for Python 3.10+, `import uno`, and a real UNO component context.
2. Installs native packages if a usable pair is missing, then repeats discovery.
3. Checks that the chosen loopback HTTP and UNO ports are free.
4. Launches the companion and a dedicated LibreOffice profile/process. The
   companion serves the already-bundled web app; no Node build is needed.
5. Opens a browser after its own bridge reports readiness. Paste the printed
   pairing token into **Connect LibreOffice**. The token stays out of URLs.

The default local URL is **http://127.0.0.1:8765**. The UNO port is 2002. Neither
service is opened to your network. Save your workbook before Ctrl+C closes the
owned office. Other running LibreOffice sessions are left alone.

The two port settings are independent. For example:

```sh
bash setup.sh --port 4010 --uno-port 2003
```

This serves the studio at **http://127.0.0.1:4010** and uses **2003** for Calc's
UNO connection. `--port 4010` alone still uses the default UNO port **2002**.

## Native package plans

| Platform        | Package manager | Native packages                         |
| --------------- | --------------- | --------------------------------------- |
| Debian / Ubuntu | apt             | `libreoffice-calc`, `python3-uno`       |
| Fedora          | dnf             | `libreoffice-calc`, `libreoffice-pyuno` |
| Arch            | pacman          | `libreoffice-fresh`, `python`           |
| macOS           | Homebrew        | `libreoffice` cask                      |
| Windows         | WinGet          | `TheDocumentFoundation.LibreOffice`     |

Package names follow the distribution/vendor repositories. The script does not
add third-party Linux repositories or perform a whole-system upgrade. On Arch,
maintain your system/database using your normal full-upgrade process if pacman
reports stale package URLs. Package failures remain visible and stop setup.

Use a normal user account. Only Linux package commands invoke `sudo`; WinGet can
request UAC approval and show installer/license prompts. Homebrew runs without
sudo. Installation requires an Internet connection. A subsequent run with valid
tools skips installation; it does not require reinstalling LibreOffice each time.

The system Python is preferred on Linux so distro UNO packages are visible.
macOS checks the selected app's `Contents/Resources/python`; Windows checks its
`program/python.exe` and prefers the `soffice.com` console launcher. These paths
follow [LibreOffice's Python documentation](https://dev.blog.documentfoundation.org/2023/12/14/libreoffice-extensions-with-python-part-2-debugging/).
`pip install uno` is not used. An installed application without a compatible
bundled Python/UNO runtime is reported as a setup failure, not as successful
native rendering.

## Options

These options work with both OS entrypoints and the shared Python script:

| Option              | Behavior                                                                  |
| ------------------- | ------------------------------------------------------------------------- |
| `--dry-run`         | Show package commands; no installation, UNO probing, server or browser    |
| `--check`           | Probe existing runtimes; no installation or launch; failure exits nonzero |
| `--install-only`    | Install/check prerequisites and stop before launch                        |
| `--no-install`      | Never invoke a package manager; fail if native prerequisites are missing  |
| `--web-only`        | Serve the browser studio without native Calc or UNO                       |
| `--with-ffmpeg`     | Also install FFmpeg for CLI file conversion/direct camera capture         |
| `--no-open`         | Start the service without opening a browser                               |
| `--python PATH`     | Use a particular matching UNO Python executable                           |
| `--lo-binary PATH`  | Use a particular LibreOffice executable                                   |
| `--port NUMBER`     | Set the local web/bridge port (default 8765)                              |
| `--uno-port NUMBER` | Set the office UNO port (default 2002)                                    |

Read-only modes need Python 3.10+ already available: the bootstrap launchers will
not install even Python when `--dry-run`, `--check`, or `--no-install` is passed.
A dry run conservatively includes native prerequisites because it does not run
an interpreter to establish whether UNO already works.

FFmpeg is optional because browser media decoding needs no FFmpeg service.
`--with-ffmpeg` uses `ffmpeg` on apt/pacman/Homebrew, `ffmpeg-free` on Fedora, and
`Gyan.FFmpeg` on WinGet. Fedora's available codecs depend on its distribution
package. Newly installed Windows PATH entries are reread for this process; if
FFmpeg still cannot be located, setup asks you to reopen the terminal.

Examples:

```sh
# Existing native runtime, another HTTP/UNO port, no browser window
python3 setup_celluloid.py --no-install --port 8877 --uno-port 2003 --no-open

# Mac with an explicit application/interpreter pair
python3 setup_celluloid.py \
  --python "/Applications/LibreOffice.app/Contents/Resources/python" \
  --lo-binary "/Applications/LibreOffice.app/Contents/MacOS/soffice"
```

```powershell
# Windows custom installation; keep paths with spaces quoted
.\setup.cmd --python "C:\Program Files\LibreOffice\program\python.exe" --lo-binary "C:\Program Files\LibreOffice\program\soffice.com"
```

## Troubleshooting

- **Package manager missing:** install Homebrew or App Installer, or install the
  prerequisites manually and use `--no-install`. Unsupported Linux distributions
  can use their own matched Calc/Python UNO packages with this option.
- **Python/UNO check fails:** use an up-to-date matching architecture/runtime.
  A venv or a different Homebrew Python may not see distribution/bundled UNO.
  Read the printed interpreter errors; use `--python` to select a working one.
  A bad explicit interpreter is not repaired by reinstalling a random office.
- **First LibreOffice launch:** finish any OS/application prompts, then rerun
  setup. The launcher stops with a diagnostic if the bridge is not ready within
  45 seconds; it does not open an unrelated process already using the port.
- **Port busy:** read which port the error names. Change `--port` for the studio,
  or `--uno-port` for LibreOffice. On a Mac, inspect an actual UNO listener with
  `lsof -nP -iTCP:2002 -sTCP:LISTEN`. If that is empty after Ctrl+C but an older
  setup still reports "busy", upgrade to 1.2.2: the earlier probe incorrectly
  rejected closed TCP connections in TIME_WAIT. Do not kill an unrelated office
  process to resolve a socket with no listener. Setup never terminates another
  application to free a port.
- **Ctrl+C cleanup:** allow a few seconds for the owned Calc process to exit.
  Version 1.2.2 restores explicit interrupt handlers and keeps cleanup running
  if Ctrl+C is pressed again. It also stops owned process-group descendants when
  an office launcher exits first. Save your workbook before stopping.
- **Camera denied:** allow your browser or terminal app in your OS's camera
  privacy settings. Device permissions cannot be granted by this installer.
- **No prompt in Arc/Chromium:** select **Webcam → Enable camera**, then read
  the persistent status under that button. A saved browser block or a quiet
  permission indicator can prevent a new popup. In the site's camera settings,
  allow the local URL or reset its permission to Ask, then reload. Keep the same
  address: `localhost` and `127.0.0.1` have separate site permissions. On macOS,
  enable Arc under **System Settings → Privacy & Security → Camera**, then quit
  and reopen Arc. See [Chromium/Chrome camera settings](https://support.google.com/chrome/answer/2693767)
  and [Apple's camera permission guide](https://support.apple.com/guide/mac-help/control-access-to-your-camera-mchlf6d108da/mac).
- **Bridge serves the app, then setup reports a 45-second timeout:** upgrade the
  extracted source to 1.2.1 or later and rerun. Version 1.2.0 compared against
  the wrong native mode name even when the bridge had started successfully.
- **Native setup blocked:** `--web-only` starts the browser studio using Python
  without installing LibreOffice. It does not claim to render actual Calc cells.
- **Source download unavailable in the local studio:** local setup does not
  build a second copy of the toolkit inside itself. Your extracted source is
  already complete; `npm ci && npm run build` enables a new local toolkit download
  if you separately install Node 22+.

The script starts local services; it does not set up login/startup services or
publish a cloud deployment. Use the [Vercel guide](VERCEL.md) for hosting.

## Verification

```sh
python3 -m unittest discover -s tests -p test_setup.py -v
```

Tests cover all package plans, existing-runtime reuse, repeated setup, failed
installs/imports, paths with spaces, dry-run/check/no-install behavior, occupied
ports, own-child readiness and cleanup. A real local HTTP smoke test checks the
browser-only server on POSIX. Package installation and native process launch are
mocked in the installer tests; they never install software on the test machine.
CI includes Linux/macOS/Windows installer-test jobs and Windows PowerShell syntax
parsing. Their first account-side run is pending. Full fresh-machine native
installation and physical cameras still need target-machine acceptance testing.
See [verification](verification.md) and [real native acceptance](../native/README.md).
