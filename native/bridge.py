#!/usr/bin/env python3
"""Loopback HTTP bridge from indexed browser frames to real LibreOffice cells.

No third-party packages are required for simulation or the HTTP layer. Real Calc
rendering needs the `uno` module provided by your LibreOffice installation.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

MAX_WIDTH = 256
MAX_HEIGHT = 144
MAX_BODY = 2_000_000
PROTOCOL = "cell-video-v1"


class RequestError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Session:
    id: str
    width: int
    height: int
    palette: tuple[int, ...]


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise RequestError(f"{name} must be an integer between {low} and {high}")
    return value


def parse_session(data: dict) -> Session:
    width = integer(data.get("width"), "width", 1, MAX_WIDTH)
    height = integer(data.get("height"), "height", 1, MAX_HEIGHT)
    palette = data.get("palette")
    if not isinstance(palette, list) or not 1 <= len(palette) <= 256:
        raise RequestError("palette must contain between 1 and 256 #RRGGBB strings")
    if any(not isinstance(c, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in palette):
        raise RequestError("palette colors must use #RRGGBB format")
    return Session(secrets.token_urlsafe(18), width, height,
                   tuple(int(c[1:], 16) for c in palette))


def changed_runs(pixels, previous, width, height):
    """Yield (row, first_column, last_column, color_index), merging row runs."""
    for row in range(height):
        column = 0
        while column < width:
            offset = row * width + column
            if previous is not None and pixels[offset] == previous[offset]:
                column += 1
                continue
            color, first = pixels[offset], column
            column += 1
            while column < width:
                offset = row * width + column
                if pixels[offset] != color or (previous is not None and pixels[offset] == previous[offset]):
                    break
                column += 1
            yield row, first, column - 1, color


class SimulatedRenderer:
    mode = "simulation"

    def start(self, session):
        self.cells = [None] * (session.width * session.height)
        self.session = session

    def render(self, runs, palette):
        for row, first, last, index in runs:
            start = row * self.session.width + first
            self.cells[start:start + last - first + 1] = [palette[index]] * (last - first + 1)

    def end(self):
        pass


class CalcRenderer:
    mode = "libreoffice"

    def __init__(self, uno_url):
        try:
            import uno
        except ImportError as error:
            raise RuntimeError("Python cannot import uno. Use the system Python with python3-uno installed; see native/README.md.") from error
        context = uno.getComponentContext()
        resolver = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", context)
        try:
            self.remote = resolver.resolve(uno_url)
        except Exception as error:
            raise RuntimeError("Cannot connect to LibreOffice UNO. Start LibreOffice with the documented --accept option.") from error
        try:
            self.desktop = self.remote.ServiceManager.createInstanceWithContext(
                "com.sun.star.frame.Desktop", self.remote)
        except Exception as error:
            raise RuntimeError("Connected to UNO, but LibreOffice could not create its Desktop service. Check the LibreOffice/Python UNO installation.") from error
        self.document = None

    def start(self, session):
        document = self.desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
        if document is None:
            raise RuntimeError("LibreOffice did not create a Calc spreadsheet")
        try:
            if not document.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
                raise RuntimeError("LibreOffice did not create a Calc spreadsheet")
            sheet = document.Sheets.getByIndex(0)
            sheet.Name = "Cell Video"
            document.lockControllers()
            try:
                area = sheet.getCellRangeByPosition(0, 0, session.width - 1, session.height - 1)
                area.Columns.Width = 350
                area.Rows.Height = 350
                document.CurrentController.ZoomValue = 70
                document.CurrentController.ShowGrid = False
            finally:
                document.unlockControllers()
        except BaseException:
            # A failed replacement must not orphan a partial document or move an
            # existing Engine session away from its successfully initialized one.
            try:
                document.close(True)
            except Exception:
                pass
            raise
        self.document, self.sheet = document, sheet

    def render(self, runs, palette):
        self.document.lockControllers()
        try:
            for row, first, last, index in runs:
                self.sheet.getCellRangeByPosition(first, row, last, row).CellBackColor = palette[index]
        finally:
            self.document.unlockControllers()

    def end(self):
        # Keep the final frame and document open for the user to save as ODS.
        pass


class Engine:
    def __init__(self, renderer):
        self.renderer = renderer
        self.session = None
        self.previous = None
        self.sequence = -1

    def start(self, data):
        session = parse_session(data)
        self.renderer.start(session)
        self.session, self.previous, self.sequence = session, None, -1
        return {"sessionId": session.id, "width": session.width, "height": session.height,
                "mode": self.renderer.mode}

    def frame(self, data):
        session = self.session
        if session is None or data.get("sessionId") != session.id:
            raise RequestError("Unknown session; create a session first", 409)
        sequence = integer(data.get("sequence"), "sequence", 0, 2**53 - 1)
        if sequence <= self.sequence:
            raise RequestError("Stale sequence; frame sequence must increase", 409)
        pixels = data.get("pixels")
        if not isinstance(pixels, list) or len(pixels) != session.width * session.height:
            raise RequestError(f"pixels must contain exactly {session.width * session.height} palette indices")
        if any(type(p) is not int or not 0 <= p < len(session.palette) for p in pixels):
            raise RequestError("Every pixel must be an integer index into the session palette")
        started = time.perf_counter()
        runs = list(changed_runs(pixels, self.previous, session.width, session.height))
        try:
            self.renderer.render(runs, session.palette)
        except Exception:
            # A partially written frame must be fully redrawn on the next request.
            self.previous = None
            raise
        self.previous, self.sequence = pixels[:], sequence
        return {"sequence": sequence, "changedCells": sum(last - first + 1 for _, first, last, _ in runs),
                "rangeWrites": len(runs), "renderMs": round((time.perf_counter() - started) * 1000, 3)}

    def end(self, data):
        if self.session is None or data.get("sessionId") != self.session.id:
            raise RequestError("Unknown session", 409)
        self.renderer.end()
        self.session, self.previous, self.sequence = None, None, -1
        return {"stopped": True}


def make_handler(engine, token, allowed_origins, web_root=None):
    origins = frozenset(allowed_origins)
    root = Path(web_root).resolve() if web_root else None

    class Handler(BaseHTTPRequestHandler):
        server_version = "CellVideoBridge/1"

        def log_message(self, format, *args):
            # Log method and path without query strings, headers, or pairing tokens.
            try:
                path = self.request_path()
            except RequestError:
                path = "[invalid request target]"
            sys.stderr.write(f"{self.client_address[0]} {self.command} {path}\n")

        def request_path(self):
            try:
                return urlsplit(self.path).path
            except ValueError as error:
                raise RequestError("Invalid request target") from error

        def reply(self, status, payload):
            body = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            self.cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def cors(self):
            origin = self.headers.get("Origin")
            if origin in origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")

        def check_origin(self):
            port = self.server.server_port
            if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                raise RequestError("Invalid loopback Host header", 403)
            origin = self.headers.get("Origin")
            if origin is not None and origin not in origins:
                raise RequestError("Origin is not allowed; configure --allow-origin", 403)

        def authenticate(self):
            self.check_origin()
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, "Bearer " + token):
                raise RequestError("Pairing token required", 401)

        def read_json(self):
            if self.headers.get("Transfer-Encoding"):
                raise RequestError("Chunked request bodies are not supported")
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise RequestError("Content-Type must be application/json", 415)
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                raise RequestError("Content-Length is required", 411)
            if not 0 < length <= MAX_BODY:
                raise RequestError("Request body exceeds the 2 MB limit", 413)
            try:
                value = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeDecodeError):
                raise RequestError("Invalid JSON body")
            if not isinstance(value, dict):
                raise RequestError("JSON body must be an object")
            return value

        def do_OPTIONS(self):
            try:
                self.request_path()
                self.check_origin()
                self.reply(200, {"ok": True})
            except RequestError as error:
                self.reply(error.status, {"error": str(error)})

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def do_DELETE(self):
            self.handle_request()

        def handle_request(self):
            try:
                path = self.request_path()
                if self.command == "GET" and root and not path.startswith(("/health", "/session", "/frame")):
                    self.check_origin()
                    self.serve_web(path)
                    return
                self.authenticate()
                if self.command == "GET" and path == "/health":
                    payload = {"ok": True, "protocol": PROTOCOL, "mode": engine.renderer.mode,
                               "maxWidth": MAX_WIDTH, "maxHeight": MAX_HEIGHT, "maxPalette": 256}
                elif self.command == "POST" and path == "/session":
                    payload = engine.start(self.read_json())
                elif self.command == "POST" and path == "/frame":
                    payload = engine.frame(self.read_json())
                elif self.command == "DELETE" and path == "/session":
                    payload = engine.end(self.read_json())
                else:
                    raise RequestError("Endpoint not found", 404)
                self.reply(200, payload)
            except RequestError as error:
                self.reply(error.status, {"error": str(error)})
            except Exception:
                # Keep UNO/server internals out of responses, report diagnostic locally.
                import traceback
                traceback.print_exc()
                self.reply(503, {"error": "Spreadsheet operation failed; inspect the companion terminal"})

        def serve_web(self, path):
            from mimetypes import guess_type
            from urllib.parse import unquote
            resolved = (root / unquote(path).lstrip("/")).resolve()
            if not resolved.is_relative_to(root):
                raise RequestError("Invalid path", 403)
            if resolved.is_dir():
                resolved /= "index.html"
            if not resolved.is_file():
                raise RequestError("File not found", 404)
            body = resolved.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", guess_type(str(resolved))[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


class BridgeServer(HTTPServer):
    # Single request at a time deliberately serializes calls into UNO.
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address


class LibreOfficeProcess:
    """Own only the dedicated process/profile started by --launch-lo."""

    def __init__(self, binary, port, headless=False):
        self.profile = Path(tempfile.mkdtemp(prefix="celluloid-lo-"))
        command = [binary, f"-env:UserInstallation={self.profile.as_uri()}",
                   f"--accept=socket,host=127.0.0.1,port={port};urp;StarOffice.ServiceManager",
                   "--norestore", "--nodefault", "--nofirststartwizard"]
        if headless:
            command.append("--headless")
        try:
            self.process = subprocess.Popen(command, start_new_session=(os.name == "posix"))
        except Exception:
            shutil.rmtree(self.profile, ignore_errors=True)
            raise

    def close(self):
        if os.name == "posix":
            # A launcher can exit before its office children. Its dedicated
            # process group still belongs to us even after the leader exits.
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            finally:
                # Reap stubborn descendants as well as the direct child. Other
                # LibreOffice instances have different process groups/profiles.
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.process.wait(timeout=3)
        elif self.process.poll() is None:
            # soffice.com/.exe may own a soffice.bin child. Stop only our
            # dedicated process tree, never all LibreOffice processes.
            try:
                subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=5, check=False)
            except (OSError, subprocess.TimeoutExpired):
                self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        shutil.rmtree(self.profile, ignore_errors=True)


def check_loopback_port(port):
    """Reject an active listener while allowing closed POSIX TIME_WAIT sockets."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if os.name == "posix":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))


def launch_renderer(binary, port, headless=False):
    # Fail before creating a process if the interpreter lacks the UNO binding.
    try:
        import uno  # noqa: F401
    except ImportError as error:
        raise RuntimeError("Python cannot import uno. Use /usr/bin/python3 after installing python3-uno.") from error
    executable = binary or shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise RuntimeError("LibreOffice executable not found; install LibreOffice Calc or pass --lo-binary PATH.")
    # Do not mistake an unrelated listener for the dedicated office we own.
    # Existing office sessions use --uno-url instead of --launch-lo.
    try:
        check_loopback_port(port)
    except OSError as error:
        raise RuntimeError(f"UNO port {port} is unavailable; choose another --uno-port or connect with --uno-url.") from error
    owned = LibreOfficeProcess(executable, port, headless)
    url = f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"
    deadline = time.monotonic() + 15
    last_error = None
    try:
        while time.monotonic() < deadline:
            if owned.process.poll() is not None:
                raise RuntimeError(f"LibreOffice exited during startup (code {owned.process.returncode}).")
            try:
                renderer = CalcRenderer(url)
                if owned.process.poll() is not None:
                    raise RuntimeError(f"LibreOffice exited during startup (code {owned.process.returncode}).")
                return renderer, owned
            except RuntimeError as error:
                last_error = error
                if owned.process.poll() is not None:
                    raise RuntimeError(f"LibreOffice exited during startup (code {owned.process.returncode}).") from error
                time.sleep(0.25)
        raise RuntimeError(f"LibreOffice was not ready within 15 seconds: {last_error}")
    except BaseException:
        owned.close()
        raise


def main():
    def shutdown(signum, frame):
        raise KeyboardInterrupt

    # The setup launcher uses SIGINT on POSIX and CTRL_BREAK on Windows so
    # normal finally blocks close the owned office/profile on terminal exit.
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, shutdown)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allow-origin", action="append", default=[], help="Exact browser origin, repeatable")
    parser.add_argument("--simulate", action="store_true", help="Exercise transport without LibreOffice; does not render actual cells")
    parser.add_argument("--launch-lo", action="store_true", help="Start a dedicated LibreOffice process automatically")
    parser.add_argument("--lo-binary", help="LibreOffice executable path for --launch-lo")
    parser.add_argument("--uno-port", type=int, default=2002, help="UNO loopback port for --launch-lo")
    parser.add_argument("--headless", action="store_true", help="Hide automatically launched LibreOffice (integration tests)")
    parser.add_argument("--uno-url", default="uno:socket,host=127.0.0.1,port=2002;urp;StarOffice.ComponentContext")
    parser.add_argument("--token-file", type=Path, help="Read a pairing token from a protected file; generate one if absent")
    parser.add_argument("--web-root", type=Path, help="Serve the built frontend locally to avoid browser private-network restrictions")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if not 1 <= args.uno_port <= 65535 or args.uno_port == args.port:
        parser.error("UNO port must be between 1 and 65535 and differ from the HTTP port")
    if args.simulate and args.launch_lo:
        parser.error("--simulate and --launch-lo cannot be combined")
    for origin in args.allow_origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            parser.error("--allow-origin must be an exact http(s) origin without path or trailing slash")
    token = secrets.token_urlsafe(32)
    if args.token_file:
        if args.token_file.exists():
            token = args.token_file.read_text().strip()
            if len(token) < 32 or any(c.isspace() for c in token):
                parser.error("token-file must contain a token of at least 32 characters without whitespace")
        else:
            args.token_file.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(args.token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(token + "\n")
    owned = None
    try:
        if args.launch_lo:
            renderer, owned = launch_renderer(args.lo_binary, args.uno_port, args.headless)
        else:
            renderer = SimulatedRenderer() if args.simulate else CalcRenderer(args.uno_url)
    except RuntimeError as error:
        parser.exit(1, f"{error}\n")
    origins = set(args.allow_origin)
    origins.update({f"http://127.0.0.1:{args.port}", f"http://localhost:{args.port}"})
    try:
        server = BridgeServer(("127.0.0.1", args.port), make_handler(Engine(renderer), token, origins, args.web_root))
    except OSError as error:
        if owned:
            owned.close()
        parser.exit(1, f"Cannot start loopback bridge: {error}\n")
    print(f"Cell video bridge ({renderer.mode}) at http://127.0.0.1:{args.port}", flush=True)
    print(f"Pairing token: {token}", flush=True)
    print("Allowed browser origins: " + ", ".join(sorted(origins)), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if owned:
            owned.close()


if __name__ == "__main__":
    main()
