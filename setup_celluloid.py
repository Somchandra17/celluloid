#!/usr/bin/env python3
"""Install native prerequisites and launch Celluloid locally on Linux, macOS or Windows."""
from __future__ import annotations

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser

from native.processes import run_bounded
from native.bridge import CalcRenderer, check_loopback_port

ROOT = Path(__file__).resolve().parent
PROBE = ('import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"; '
         'import uno; assert uno.getComponentContext() is not None; '
         'print("CELLULOID_UNO_READY")')


class SetupError(RuntimeError):
    pass


def unique_paths(paths):
    result, seen = [], set()
    for value in paths:
        if not value:
            continue
        path = Path(value).expanduser().absolute()
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def office_candidates(system, environment=None):
    environment = os.environ if environment is None else environment
    paths = [shutil.which("libreoffice"), shutil.which("soffice")]
    if system == "Windows":
        paths = [candidate for value in paths if value
                 for candidate in (Path(value).with_suffix(".com"), Path(value))]
    if system == "Darwin":
        paths = [Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
                 Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice", *paths]
    elif system == "Windows":
        for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
            if environment.get(variable):
                program = Path(environment[variable]) / "LibreOffice/program"
                paths.extend([program / "soffice.com", program / "soffice.exe"])
        if environment.get("LOCALAPPDATA"):
            program = Path(environment["LOCALAPPDATA"]) / "Programs/LibreOffice/program"
            paths.extend([program / "soffice.com", program / "soffice.exe"])
        try:
            import winreg
            for access in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                        r"SOFTWARE\LibreOffice\UNO\InstallPath", 0,
                                        winreg.KEY_READ | access) as key:
                        program = Path(winreg.QueryValueEx(key, "")[0])
                        paths.extend([program / "soffice.com", program / "soffice.exe"])
                except OSError:
                    pass
        except ImportError:
            pass
    return unique_paths(paths)


def find_office(system, explicit=None):
    if explicit:
        path = Path(explicit).expanduser().absolute()
        if not path.is_file():
            raise SetupError(f"LibreOffice executable does not exist: {path}")
        return path
    return next((path for path in office_candidates(system) if path.is_file()), None)


def python_candidates(system, office=None, explicit=None):
    if explicit:
        return unique_paths([explicit])
    paths = []
    if office:
        if system == "Darwin":
            paths.append(office.parent.parent / "Resources/python")
        elif system == "Windows":
            paths.append(office.parent / "python.exe")
        else:
            paths.append(office.parent / "python")
    if system == "Linux":
        paths.append("/usr/bin/python3")
    paths.extend([sys.executable, shutil.which("python3"), shutil.which("python")])
    return unique_paths(paths)


def find_uno_python(system, office=None, explicit=None):
    errors = []
    for path in python_candidates(system, office, explicit):
        if not path.is_file():
            errors.append(f"{path}: not found")
            continue
        try:
            result = run_bounded([str(path), "-c", PROBE], 12, stdout_limit=4096,
                                 stderr_limit=4096)
            if b"CELLULOID_UNO_READY" in result.stdout.splitlines():
                return path, errors
            errors.append(f"{path}: UNO did not return a component context")
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            detail = getattr(error, "stderr", b"") or b""
            detail = detail.decode("utf-8", errors="replace").strip().splitlines()
            errors.append(f"{path}: {detail[-1] if detail else str(error)}")
    return None, errors


def package_manager(system):
    names = {"Darwin": ("brew",), "Windows": ("winget",),
             "Linux": ("apt-get", "dnf", "pacman")}.get(system, ())
    for name in names:
        executable = shutil.which(name)
        if executable:
            return name, executable
    if system == "Darwin":
        for path in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
            if Path(path).is_file():
                return "brew", path
    raise SetupError("No supported package manager found. Install Homebrew on macOS "
                     "(https://brew.sh/), App Installer/WinGet on Windows, or use an "
                     "apt/dnf/pacman Linux system. Already-installed runtimes can use --no-install.")


def installation_commands(system, native=True, ffmpeg=False):
    if not native and not ffmpeg:
        return []
    manager, executable = package_manager(system)
    if manager == "brew":
        commands = [[executable, "install", "--cask", "libreoffice"]] if native else []
        if ffmpeg:
            commands.append([executable, "install", "ffmpeg"])
        return commands
    if manager == "winget":
        packages = (["TheDocumentFoundation.LibreOffice"] if native else [])
        packages += ["Gyan.FFmpeg"] if ffmpeg else []
        return [[executable, "install", "--id", package, "--exact", "--source", "winget"]
                for package in packages]
    if manager == "apt-get":
        packages = ["libreoffice-calc", "python3-uno"] if native else []
        packages += ["ffmpeg"] if ffmpeg else []
        return [[executable, "update"], [executable, "install", "-y", *packages]]
    if manager == "dnf":
        packages = ["libreoffice-calc", "libreoffice-pyuno"] if native else []
        packages += ["ffmpeg-free"] if ffmpeg else []
        return [[executable, "install", "-y", *packages]]
    packages = ["libreoffice-fresh", "python"] if native else []
    packages += ["ffmpeg"] if ffmpeg else []
    # Never perform a partial database upgrade or a whole-system upgrade here.
    return [[executable, "-S", "--needed", *packages]]


def display_command(command, system):
    return subprocess.list2cmdline(command) if system == "Windows" else shlex.join(command)


def run_installation(commands, system):
    for command in commands:
        actual = list(command)
        if system == "Linux" and os.geteuid() != 0:
            sudo = shutil.which("sudo")
            if not sudo:
                raise SetupError("Package installation needs sudo. Ask your administrator to install the printed packages.")
            actual = [sudo, *actual]
        print("Installing: " + display_command(actual, system), flush=True)
        try:
            # Use an argument list, never a shell. Package-manager/UAC prompts stay visible.
            subprocess.run(actual, check=True)
        except (OSError, subprocess.CalledProcessError) as error:
            raise SetupError("Package installation did not finish. Resolve the package-manager "
                             "message above, then rerun setup. Existing documents were not changed.") from error


def refresh_windows_path():
    """See new WinGet/Python PATH entries in this process without changing the registry."""
    try:
        import winreg
        paths = os.environ.get("PATH", "").split(os.pathsep)
        for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                          (winreg.HKEY_CURRENT_USER, "Environment")):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    paths.extend(os.path.expandvars(winreg.QueryValueEx(handle, "Path")[0]).split(os.pathsep))
            except OSError:
                pass
        os.environ["PATH"] = os.pathsep.join(dict.fromkeys(paths))
    except ImportError:
        pass


def ensure_ports(http_port, uno_port=None):
    for port, label, option in ((http_port, "Web/bridge", "--port"),
                                (uno_port, "LibreOffice UNO", "--uno-port")):
        if port is None:
            continue
        try:
            check_loopback_port(port)
        except OSError as error:
            raise SetupError(f"{label} port {port} is busy. Choose {option} with a free port. "
                             "--port sets the web address; --uno-port sets LibreOffice's port.") from error


def stop_bridge(process, system):
    if process.poll() is not None:
        return
    try:
        process.send_signal(signal.CTRL_BREAK_EVENT if system == "Windows" else signal.SIGINT)
        process.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def launch_bridge(python, office, args, system):
    ensure_ports(args.port, args.uno_port)
    command = [str(python), "-u", str(ROOT / "native/bridge.py"), "--launch-lo",
               "--lo-binary", str(office), "--web-root", str(ROOT / "dist"),
               "--port", str(args.port), "--uno-port", str(args.uno_port)]
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if system == "Windows" else {"start_new_session": True}
    environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    process = subprocess.Popen(command, cwd=ROOT, env=environment, bufsize=0, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, **options)
    ready = threading.Event()
    url = f"http://127.0.0.1:{args.port}"

    def output():
        for line in process.stdout:
            text = line.decode("utf-8", errors="replace")
            print(text, end="", flush=True)
            # Only open after OUR child's readiness message, never an unrelated listener.
            if text.strip() == f"Cell video bridge ({CalcRenderer.mode}) at {url}":
                ready.set()

    reader = threading.Thread(target=output, daemon=True)
    reader.start()
    try:
        started = time.monotonic()
        while process.poll() is None and not ready.wait(.1):
            if time.monotonic() - started > 45:
                raise SetupError("The bridge did not become ready within 45 seconds. Check LibreOffice first-launch prompts and the UNO runtime.")
        if process.poll() is not None:
            reader.join(timeout=1)
            raise SetupError(f"Bridge exited during startup (code {process.returncode}).")
        print(f"\nOpen {url}, select Connect LibreOffice, and paste the token above.", flush=True)
        print("Keep this terminal open. Save your workbook before Ctrl+C stops the owned Calc process.", flush=True)
        if not args.no_open:
            threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        return process.wait()
    except KeyboardInterrupt:
        print("\nStopping Celluloid...", flush=True)
        return 130
    finally:
        # A second Ctrl+C must not interrupt shutdown halfway through and leave
        # the child/office alive. Cleanup has bounded graceful/forced waits.
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            stop_bridge(process, system)
            reader.join(timeout=2)
            process.stdout.close()
        finally:
            signal.signal(signal.SIGINT, previous)


def serve_web(args):
    class Handler(SimpleHTTPRequestHandler):
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript"}

        def list_directory(self, path):
            self.send_error(404)

        def end_headers(self):
            self.send_header("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
            self.send_header("X-Content-Type-Options", "nosniff")
            super().end_headers()

    ensure_ports(args.port)
    handler = functools.partial(Handler, directory=str(ROOT / "dist"))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        url = f"http://127.0.0.1:{args.port}"
        print(f"Browser studio at {url}. Ctrl+C stops it. Native Calc is not connected.", flush=True)
        if not args.no_open:
            threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return 130
    return 0


def make_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print package commands without installing, probing UNO or starting anything")
    parser.add_argument("--check", action="store_true", help="Check installed tools; do not install or launch")
    parser.add_argument("--no-install", action="store_true", help="Use existing tools; never invoke a package manager")
    parser.add_argument("--install-only", action="store_true", help="Install/check tools and exit without launching")
    parser.add_argument("--web-only", action="store_true", help="Serve browser studio only; LibreOffice and UNO are not required")
    parser.add_argument("--with-ffmpeg", action="store_true", help="Also install FFmpeg for direct terminal video/camera decoding")
    parser.add_argument("--python", dest="uno_python", help="Full path to a matching UNO-enabled Python 3.10+")
    parser.add_argument("--lo-binary", help="Full path to LibreOffice/soffice")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--uno-port", type=int, default=2002)
    parser.add_argument("--no-open", action="store_true", help="Do not open a browser window automatically")
    return parser


def main(argv=None):
    signal.signal(signal.SIGINT, signal.default_int_handler)
    parser = make_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535 or not 1 <= args.uno_port <= 65535 or args.port == args.uno_port:
        parser.error("Ports must be different integers between 1 and 65535")
    system = platform.system()
    try:
        if sys.version_info < (3, 10):
            raise SetupError("Use Python 3.10 or newer, or the setup.sh / setup.cmd entrypoint.")
        if not (ROOT / "dist/index.html").is_file() or not (ROOT / "native/bridge.py").is_file():
            raise SetupError("Extract the complete source ZIP or clone the repository. Keep this script beside dist/ and native/.")
        office = None if args.web_only else find_office(system, args.lo_binary)
        if args.uno_python and not Path(args.uno_python).expanduser().is_file():
            raise SetupError(f"The --python interpreter does not exist: {args.uno_python}")
        python, errors = (None, []) if args.web_only or args.dry_run else find_uno_python(system, office, args.uno_python)
        missing_native = not args.web_only and (office is None or python is None)
        missing_ffmpeg = args.with_ffmpeg and not shutil.which("ffmpeg")
        print(f"Celluloid setup — {system}\nSource: {ROOT}", flush=True)
        if args.dry_run:
            commands = [] if args.no_install else installation_commands(system, missing_native, missing_ffmpeg)
            for command in commands:
                print("Would install: " + display_command(command, system))
            print("Would check the matching UNO runtime and launch the local studio." if not args.web_only
                  else "Would serve the browser-only studio; no native packages required.")
            print("Dry run: no package manager, UNO interpreter, server or browser was started.")
            return 0
        if not args.check and not args.no_install and (missing_native or missing_ffmpeg):
            if args.uno_python and not python and not args.web_only:
                raise SetupError("The explicit --python interpreter did not pass the UNO check. "
                                 "Fix that interpreter or omit --python for automatic discovery.\n" + "\n".join(errors))
            commands = installation_commands(system, missing_native, missing_ffmpeg)
            for command in commands:
                print("Required: " + display_command(command, system), flush=True)
            run_installation(commands, system)
            if system == "Windows":
                refresh_windows_path()
            if not args.web_only:
                office = find_office(system, args.lo_binary)
                python, errors = find_uno_python(system, office, args.uno_python)
        if not args.web_only and (office is None or python is None):
            details = "\n".join(errors)
            raise SetupError(f"A working LibreOffice + Python 3.10+ UNO pair is required.\n"
                             f"LibreOffice: {office or 'not found'}\n{details}\n"
                             "Try --python /full/path/to/uno-python and --lo-binary /full/path/to/soffice.\n"
                             "pip install uno is not the LibreOffice binding. Use --web-only for browser mode.")
        if missing_ffmpeg and not shutil.which("ffmpeg"):
            # WinGet can finish successfully before a new FFmpeg PATH reaches this process.
            raise SetupError("FFmpeg is not on this terminal's PATH. Open a new terminal after installation and rerun setup.")
        if not args.web_only:
            print(f"LibreOffice: {office}\nUNO Python: {python}", flush=True)
        if args.check or args.install_only:
            print("Setup checks passed. Rerun without --check/--install-only to start.")
            return 0
        return serve_web(args) if args.web_only else launch_bridge(python, office, args, system)
    except KeyboardInterrupt:
        print("\nSetup interrupted. Rerun when ready.", file=sys.stderr)
        return 130
    except (SetupError, OSError) as error:
        print(f"celluloid setup: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
