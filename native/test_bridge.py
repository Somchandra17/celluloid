"""Run with: python3 -m unittest discover -s native -v."""

import http.client
import io
import json
import os
import select
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

from bridge import (BridgeServer, CalcRenderer, Engine, LibreOfficeProcess, RequestError,
                    SimulatedRenderer, changed_runs, launch_renderer, make_handler, main)


class FrameTests(unittest.TestCase):
    def setUp(self):
        self.renderer = SimulatedRenderer()
        self.engine = Engine(self.renderer)
        self.session = self.engine.start({"width": 4, "height": 2, "palette": ["#000000", "#ffffff"]})

    def frame(self, pixels, sequence=0):
        return self.engine.frame({"sessionId": self.session["sessionId"], "sequence": sequence, "pixels": pixels})

    def test_first_frame_groups_only_within_rows(self):
        result = self.frame([1, 1, 1, 0, 0, 0, 1, 1])
        self.assertEqual(result["changedCells"], 8)
        self.assertEqual(result["rangeWrites"], 4)
        self.assertEqual(self.renderer.cells, [0xffffff] * 3 + [0] * 3 + [0xffffff] * 2)

    def test_unchanged_frame_performs_no_writes(self):
        self.frame([0] * 8)
        result = self.frame([0] * 8, 1)
        self.assertEqual((result["changedCells"], result["rangeWrites"]), (0, 0))

    def test_only_changed_cells_are_updated(self):
        self.frame([0] * 8)
        result = self.frame([0, 1, 1, 0, 0, 0, 1, 0], 1)
        self.assertEqual((result["changedCells"], result["rangeWrites"]), (3, 2))

    def test_invalid_and_stale_frames_do_not_change_state(self):
        self.frame([0] * 8, 5)
        for sequence, pixels in [(5, [1] * 8), (4, [1] * 8), (6, [2] * 8), (6, [True] * 8), (6, [1])]:
            with self.subTest(sequence=sequence, pixels=pixels):
                with self.assertRaises(RequestError):
                    self.frame(pixels, sequence)
        self.assertEqual(self.renderer.cells, [0] * 8)
        self.assertEqual(self.engine.sequence, 5)

    def test_partial_render_failure_forces_full_next_frame(self):
        self.frame([0] * 8)
        render = self.renderer.render

        def fail(runs, palette):
            render(runs[:1], palette)
            raise RuntimeError("injected partial write")

        self.renderer.render = fail
        with self.assertRaises(RuntimeError):
            self.frame([1] * 8, 1)
        self.renderer.render = render
        result = self.frame([0] * 8, 2)
        self.assertEqual(result["changedCells"], 8)
        self.assertEqual(self.renderer.cells, [0] * 8)

    def test_invalid_session_geometry_and_palette_rejected(self):
        for field, value in [("width", 257), ("height", 145), ("width", True), ("palette", []), ("palette", ["red"])]:
            data = {"width": 4, "height": 2, "palette": ["#000000"]}
            data[field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(RequestError):
                    self.engine.start(data)

    def test_changed_run_boundaries(self):
        result = list(changed_runs([1, 1, 1, 1], [0, 1, 0, 0], 4, 1))
        self.assertEqual(result, [(0, 0, 0, 1), (0, 2, 3, 1)])


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        Path(cls.directory.name, "index.html").write_text("<html>Celluloid</html>")
        cls.server = BridgeServer(("127.0.0.1", 0), make_handler(
            Engine(SimulatedRenderer()), "test-token", {"http://localhost:5173"}, cls.directory.name))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.directory.cleanup()

    def request(self, method, path, body=None, extra_headers=None, authenticate=True):
        headers = {"Origin": "http://localhost:5173"}
        if authenticate:
            headers["Authorization"] = "Bearer test-token"
        if isinstance(body, dict):
            body = json.dumps(body)
            headers["Content-Type"] = "application/json"
        headers.update(extra_headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        content = response.read()
        result = response.status, dict(response.getheaders()), content
        connection.close()
        return result

    def test_authentication_and_origin_are_both_required(self):
        self.assertEqual(self.request("GET", "/health", authenticate=False)[0], 401)
        self.assertEqual(self.request("GET", "/health", extra_headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/health", extra_headers={"Host": "evil.example"})[0], 403)
        status, _, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["mode"], "simulation")

    def test_private_network_cors_preflight(self):
        status, headers, _ = self.request("OPTIONS", "/frame", authenticate=False)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://localhost:5173")
        self.assertEqual(headers["Access-Control-Allow-Private-Network"], "true")

    def test_session_frame_stop_roundtrip(self):
        status, _, body = self.request("POST", "/session", {"width": 2, "height": 1, "palette": ["#ffffff"]})
        self.assertEqual(status, 200)
        session = json.loads(body)["sessionId"]
        frame = {"sessionId": session, "sequence": 0, "pixels": [0, 0]}
        status, _, body = self.request("POST", "/frame", frame)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["changedCells"], 2)
        self.assertEqual(self.request("POST", "/frame", frame)[0], 409)
        self.assertEqual(self.request("DELETE", "/session", {"sessionId": session})[0], 200)
        self.assertEqual(self.request("POST", "/frame", frame)[0], 409)

    def test_malformed_and_oversized_requests(self):
        self.assertEqual(self.request("POST", "/session", "{", {"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.request("POST", "/session", "[]", {"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.request("POST", "/session", "{}", {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("POST", "/session", "", {"Content-Type": "application/json", "Content-Length": "2000001"})[0], 413)

    def test_malformed_absolute_target_returns_400_without_crashing_or_logging_query(self):
        with patch("bridge.sys.stderr", new_callable=io.StringIO) as diagnostic:
            for method in ("GET", "OPTIONS"):
                with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=2) as connection:
                    connection.sendall((f"{method} http://[broken/?token=hidden-token HTTP/1.1\r\n"
                                        f"Host: 127.0.0.1:{self.server.server_port}\r\n\r\n").encode())
                    response = http.client.HTTPResponse(connection)
                    response.begin()
                    self.assertEqual(response.status, 400)
                    self.assertEqual(json.loads(response.read()), {"error": "Invalid request target"})
                    response.close()
            self.assertNotIn("hidden-token", diagnostic.getvalue())
            self.assertNotIn("Traceback", diagnostic.getvalue())
        self.assertEqual(self.request("GET", "/health")[0], 200)

    def test_static_site_without_token_and_traversal_protection(self):
        status, headers, body = self.request("GET", "/", authenticate=False)
        self.assertEqual(status, 200)
        self.assertIn(b"Celluloid", body)
        self.assertEqual(headers["Permissions-Policy"], "camera=(self), microphone=(), geolocation=()")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.request("GET", "/%2e%2e/bridge.py", authenticate=False)[0], 403)


class LaunchTests(unittest.TestCase):
    def test_occupied_uno_port_does_not_launch_or_connect_to_another_process(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with patch.dict("sys.modules", {"uno": object()}), patch("bridge.LibreOfficeProcess") as launch, patch(
                    "bridge.CalcRenderer") as renderer:
                with self.assertRaisesRegex(RuntimeError, "UNO port .* unavailable"):
                    launch_renderer("/usr/bin/libreoffice", port)
                launch.assert_not_called()
                renderer.assert_not_called()

    def test_startup_exit_during_connection_rejects_renderer_and_cleans_up(self):
        with patch.dict("sys.modules", {"uno": object()}), patch("bridge.socket.socket"), patch(
                "bridge.LibreOfficeProcess") as launch, patch("bridge.CalcRenderer"):
            owned = launch.return_value
            owned.process.poll.side_effect = [None, 1, 1]
            owned.process.returncode = 1
            with self.assertRaisesRegex(RuntimeError, "exited during startup"):
                launch_renderer("/usr/bin/libreoffice", 2002)
            owned.close.assert_called_once()

    def test_separate_profile_and_loopback_arguments(self):
        with patch("bridge.subprocess.Popen") as spawn, patch("bridge.os.killpg"):
            spawn.return_value.poll.return_value = 0
            owned = LibreOfficeProcess("/usr/bin/libreoffice", 2003, headless=True)
            profile = owned.profile
            command = spawn.call_args.args[0]
            self.assertIn("--accept=socket,host=127.0.0.1,port=2003;urp;StarOffice.ServiceManager", command)
            self.assertIn("-env:UserInstallation=" + profile.as_uri(), command)
            self.assertIn("--headless", command)
            self.assertTrue(profile.is_dir())
            owned.close()
            self.assertFalse(profile.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX owned process group")
    def test_office_child_is_stopped_even_after_launcher_process_exits(self):
        child = '''
import json, os, signal, socket, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
listener = socket.socket()
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("127.0.0.1", 0))
listener.listen()
print(json.dumps({"port": listener.getsockname()[1]}), flush=True)
time.sleep(30)
'''
        parent = "import subprocess, sys; subprocess.Popen([sys.executable, '-u', '-c', " + repr(child) + "])"
        with tempfile.TemporaryDirectory() as directory:
            owned = LibreOfficeProcess.__new__(LibreOfficeProcess)
            owned.profile = Path(directory) / "owned-profile"
            owned.profile.mkdir()
            owned.process = subprocess.Popen([sys.executable, "-u", "-c", parent],
                                             start_new_session=True, stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL)
            try:
                self.assertTrue(select.select([owned.process.stdout], [], [], 5)[0], "child did not start")
                port = json.loads(owned.process.stdout.readline())["port"]
                self.assertEqual(owned.process.wait(timeout=5), 0)
                owned.close()
                deadline = time.monotonic() + 2
                while True:
                    with socket.socket() as probe:
                        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        try:
                            probe.bind(("127.0.0.1", port))
                            break
                        except OSError:
                            if time.monotonic() >= deadline:
                                self.fail("owned office child still holds its port after close")
                    time.sleep(.01)
                self.assertFalse(owned.profile.exists())
            finally:
                try:
                    os.killpg(owned.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                owned.process.wait(timeout=5)
                owned.process.stdout.close()

    def test_failed_launch_removes_temporary_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory, "owned")
            profile.mkdir()
            with patch("bridge.tempfile.mkdtemp", return_value=str(profile)), patch(
                    "bridge.subprocess.Popen", side_effect=OSError("missing executable")):
                with self.assertRaises(OSError):
                    LibreOfficeProcess("/missing/libreoffice", 2002)
            self.assertFalse(profile.exists())

    def test_windows_cleanup_targets_only_the_owned_process_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            owned = LibreOfficeProcess.__new__(LibreOfficeProcess)
            owned.profile = Path(directory) / "profile"
            owned.profile.mkdir()
            owned.process = MagicMock()
            owned.process.pid = 12345
            owned.process.poll.return_value = None
            with patch("bridge.os.name", "nt"), patch("bridge.subprocess.run") as terminate_tree:
                owned.close()
            self.assertEqual(terminate_tree.call_args.args[0], ["taskkill", "/PID", "12345", "/T", "/F"])
            owned.process.wait.assert_called_once_with(timeout=3)
            self.assertFalse(owned.profile.exists())


class CalcLifecycleTests(unittest.TestCase):
    def test_render_failure_unlocks_controllers(self):
        renderer = CalcRenderer.__new__(CalcRenderer)
        renderer.document = MagicMock()
        renderer.sheet = MagicMock()
        renderer.sheet.getCellRangeByPosition.side_effect = RuntimeError("cell formatting failed")
        with self.assertRaisesRegex(RuntimeError, "cell formatting failed"):
            renderer.render([(0, 0, 1, 0)], [0])
        renderer.document.lockControllers.assert_called_once()
        renderer.document.unlockControllers.assert_called_once()

    def test_failed_replacement_closes_partial_document_and_preserves_active_session(self):
        renderer = CalcRenderer.__new__(CalcRenderer)
        renderer.desktop = MagicMock()
        renderer.document = None
        good_document, partial_document = MagicMock(), MagicMock()
        renderer.desktop.loadComponentFromURL.side_effect = [good_document, partial_document]
        engine = Engine(renderer)
        engine.start({"width": 2, "height": 1, "palette": ["#000000"]})
        engine.frame({"sessionId": engine.session.id, "sequence": 0, "pixels": [0, 0]})
        good_sheet, session = renderer.sheet, engine.session
        partial_area = partial_document.Sheets.getByIndex.return_value.getCellRangeByPosition.return_value
        type(partial_area.Rows).Height = PropertyMock(side_effect=RuntimeError("row sizing failed"))
        with self.assertRaisesRegex(RuntimeError, "row sizing failed"):
            engine.start({"width": 3, "height": 2, "palette": ["#ffffff"]})
        partial_document.unlockControllers.assert_called_once()
        partial_document.close.assert_called_once_with(True)
        good_document.close.assert_not_called()
        self.assertIs(renderer.document, good_document)
        self.assertIs(renderer.sheet, good_sheet)
        self.assertIs(engine.session, session)
        self.assertEqual(engine.sequence, 0)
        self.assertEqual(engine.previous, [0, 0])

    def test_non_calc_document_is_closed_when_rejected(self):
        renderer = CalcRenderer.__new__(CalcRenderer)
        renderer.document = None
        renderer.desktop = MagicMock()
        document = renderer.desktop.loadComponentFromURL.return_value
        document.supportsService.return_value = False
        with self.assertRaisesRegex(RuntimeError, "did not create a Calc spreadsheet"):
            renderer.start(type("Session", (), {"width": 2, "height": 1})())
        document.close.assert_called_once_with(True)
        self.assertIsNone(renderer.document)


class ShutdownTests(unittest.TestCase):
    def test_launcher_shutdown_signal_uses_normal_owned_office_cleanup(self):
        import signal

        renderer, owned = MagicMock(), MagicMock()
        renderer.mode = "native"
        with patch("bridge.signal.signal") as register, patch("bridge.sys.argv", ["bridge.py", "--launch-lo"]), patch(
                "bridge.launch_renderer", return_value=(renderer, owned)), patch("bridge.BridgeServer") as server, patch(
                "bridge.sys.stdout", new_callable=io.StringIO):
            def interrupt():
                handler = next(call.args[1] for call in register.call_args_list if call.args[0] == signal.SIGTERM)
                handler(signal.SIGTERM, None)

            server.return_value.serve_forever.side_effect = interrupt
            main()
        owned.close.assert_called_once()
        server.return_value.server_close.assert_called_once()

if __name__ == "__main__":
    unittest.main()
