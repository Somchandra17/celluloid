"""Installer plans/lifecycle tests; package installation is never executed."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import signal
import socket
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("celluloid_setup", ROOT / "setup_celluloid.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class PackagePlanTests(unittest.TestCase):
    def test_each_supported_package_manager_uses_native_uno_packages(self):
        cases = [
            ("Linux", "apt-get", ["apt-get", "install", "-y", "libreoffice-calc", "python3-uno"]),
            ("Linux", "dnf", ["dnf", "install", "-y", "libreoffice-calc", "libreoffice-pyuno"]),
            ("Linux", "pacman", ["pacman", "-S", "--needed", "libreoffice-fresh", "python"]),
            ("Darwin", "brew", ["brew", "install", "--cask", "libreoffice"]),
            ("Windows", "winget", ["winget", "install", "--id", "TheDocumentFoundation.LibreOffice", "--exact", "--source", "winget"]),
        ]
        for system, manager, expected in cases:
            with self.subTest(manager=manager), patch.object(setup, "package_manager", return_value=(manager, manager)):
                commands = setup.installation_commands(system)
                self.assertEqual(commands[-1], expected)
                if manager == "apt-get":
                    self.assertEqual(commands[0], ["apt-get", "update"])
                self.assertNotIn("-Sy", str(commands))

    def test_optional_ffmpeg_does_not_install_office_for_web_mode(self):
        for system, manager, package in [("Linux", "dnf", "ffmpeg-free"),
                                          ("Darwin", "brew", "ffmpeg"),
                                          ("Windows", "winget", "Gyan.FFmpeg")]:
            with self.subTest(system=system), patch.object(setup, "package_manager", return_value=(manager, manager)):
                command = setup.installation_commands(system, native=False, ffmpeg=True)
                self.assertIn(package, command[0])
                self.assertNotIn("libreoffice", str(command).lower())
        with patch.object(setup, "package_manager") as manager:
            self.assertEqual(setup.installation_commands("Unknown", native=False), [])
            manager.assert_not_called()

    def test_only_package_manager_command_is_elevated_and_no_shell_is_used(self):
        with patch.object(setup.os, "geteuid", return_value=1000, create=True), patch.object(
                setup.shutil, "which", return_value="/usr/bin/sudo"), patch.object(setup.subprocess, "run") as run:
            setup.run_installation([["apt-get", "install", "libreoffice-calc"]], "Linux")
            run.assert_called_once_with(["/usr/bin/sudo", "apt-get", "install", "libreoffice-calc"], check=True)

    def test_failed_install_is_not_reported_as_success(self):
        with patch.object(setup.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["brew"])):
            with self.assertRaisesRegex(setup.SetupError, "did not finish"):
                setup.run_installation([["brew", "install", "--cask", "libreoffice"]], "Darwin")

    def test_missing_package_manager_has_actionable_error(self):
        with patch.object(setup.shutil, "which", return_value=None):
            with self.assertRaisesRegex(setup.SetupError, "No supported package manager"):
                setup.package_manager("Unknown")


class RuntimeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX TIME_WAIT reuse")
    def test_closed_connections_do_not_report_either_port_busy(self):
        def retired_port():
            with socket.socket() as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(("127.0.0.1", 0))
                server.listen()
                port = server.getsockname()[1]
                with socket.create_connection(("127.0.0.1", port)) as client:
                    accepted, _ = server.accept()
                    accepted.close()  # Server actively closes: its port enters TIME_WAIT.
                    self.assertEqual(client.recv(1), b"")
            return port

        setup.ensure_ports(retired_port(), retired_port())

    def test_busy_uno_diagnostic_identifies_the_uno_option(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            with self.assertRaisesRegex(setup.SetupError, "LibreOffice UNO.*--uno-port"):
                setup.ensure_ports(None, server.getsockname()[1])

    def test_mac_python_is_selected_from_the_same_app_as_soffice(self):
        office = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        candidates = setup.python_candidates("Darwin", office)
        self.assertEqual(candidates[0], Path("/Applications/LibreOffice.app/Contents/Resources/python").absolute())

    def test_windows_discovers_paths_with_spaces_and_console_launcher(self):
        with tempfile.TemporaryDirectory(prefix="office with spaces ") as directory:
            program = Path(directory) / "LibreOffice/program"
            program.mkdir(parents=True)
            (program / "soffice.exe").touch()
            (program / "soffice.com").touch()
            with patch.dict(setup.os.environ, {"ProgramFiles": directory}, clear=True), patch.object(
                    setup.shutil, "which", return_value=None):
                office = setup.find_office("Windows")
            self.assertEqual(office, program / "soffice.com")
            self.assertEqual(setup.python_candidates("Windows", office)[0], program / "python.exe")

    def test_system_python_is_preferred_over_a_venv_on_linux(self):
        self.assertEqual(setup.python_candidates("Linux")[0], Path("/usr/bin/python3").absolute())

    def test_probe_rejects_failed_import_then_accepts_real_component_context(self):
        candidates = [Path(sys.executable), Path(__file__)]
        error = subprocess.CalledProcessError(1, [], stderr=b"ImportError: incompatible UNO")
        good = subprocess.CompletedProcess([], 0, b"CELLULOID_UNO_READY\n", b"")
        with patch.object(setup, "python_candidates", return_value=candidates), patch.object(
                setup, "run_bounded", side_effect=[error, good]) as probe:
            selected, errors = setup.find_uno_python("Linux")
        self.assertEqual(selected, candidates[1])
        self.assertIn("incompatible UNO", errors[0])
        self.assertEqual(probe.call_args.args[0][1], "-c")
        self.assertIn("uno.getComponentContext()", probe.call_args.args[0][2])

    def test_explicit_missing_office_is_not_silently_replaced(self):
        with self.assertRaisesRegex(setup.SetupError, "does not exist"):
            setup.find_office("Darwin", ROOT / "not-installed/soffice")

    def test_occupied_port_is_rejected_before_startup(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            with self.assertRaisesRegex(setup.SetupError, "is busy"):
                setup.ensure_ports(listener.getsockname()[1])


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.stack.enter_context(contextlib.redirect_stderr(self.output))
        self.stack.enter_context(patch.object(setup.platform, "system", return_value="Linux"))
        self.office = self.stack.enter_context(patch.object(setup, "find_office", return_value=Path("/office/soffice")))
        self.python = self.stack.enter_context(patch.object(setup, "find_uno_python", return_value=(Path(sys.executable), [])))
        self.install = self.stack.enter_context(patch.object(setup, "run_installation"))
        self.launch = self.stack.enter_context(patch.object(setup, "launch_bridge", return_value=0))
        self.web = self.stack.enter_context(patch.object(setup, "serve_web", return_value=0))

    def test_repeated_setup_uses_existing_runtime_without_package_changes(self):
        self.assertEqual(setup.main([]), 0)
        self.install.assert_not_called()
        self.launch.assert_called_once()
        self.assertEqual(self.launch.call_args.args[1], Path("/office/soffice"))

    def test_dry_run_never_probes_installs_or_launches(self):
        self.office.return_value = None
        with patch.object(setup, "installation_commands", return_value=[["apt-get", "install", "python3-uno"]]):
            self.assertEqual(setup.main(["--dry-run"]), 0)
        self.python.assert_not_called()
        self.install.assert_not_called()
        self.launch.assert_not_called()
        self.assertIn("Would install", self.output.getvalue())

    def test_install_then_rediscover_the_matching_runtime(self):
        self.office.side_effect = [None, Path("/new office/soffice")]
        self.python.side_effect = [(None, ["not installed"]), (Path("/new office/python"), [])]
        with patch.object(setup, "installation_commands", return_value=[["apt-get", "install", "python3-uno"]]):
            self.assertEqual(setup.main(["--install-only"]), 0)
        self.install.assert_called_once()
        self.assertEqual(self.office.call_count, 2)
        self.launch.assert_not_called()

    def test_check_reports_missing_uno_without_modifying_machine(self):
        self.python.return_value = (None, ["UNO import failed"])
        self.assertEqual(setup.main(["--check"]), 1)
        self.install.assert_not_called()
        self.launch.assert_not_called()
        self.assertIn("UNO import failed", self.output.getvalue())

    def test_no_install_still_refuses_unusable_native_runtime(self):
        self.python.return_value = (None, ["UNO unavailable"])
        with patch.object(setup, "installation_commands") as plan:
            self.assertEqual(setup.main(["--no-install"]), 1)
            plan.assert_not_called()
        self.install.assert_not_called()

    def test_browser_mode_does_not_require_or_install_office(self):
        self.assertEqual(setup.main(["--web-only"]), 0)
        self.office.assert_not_called()
        self.python.assert_not_called()
        self.install.assert_not_called()
        self.launch.assert_not_called()
        self.web.assert_called_once()

    def test_missing_explicit_python_fails_before_installation(self):
        self.assertEqual(setup.main(["--python", str(ROOT / "not-a-python")]), 1)
        self.install.assert_not_called()

    def test_invalid_ports_fail_before_any_actions(self):
        with self.assertRaises(SystemExit):
            setup.main(["--port", "2002", "--uno-port", "2002"])
        self.office.assert_not_called()
        self.install.assert_not_called()


class LaunchTests(unittest.TestCase):
    def test_owned_child_readiness_opens_browser_and_always_runs_cleanup(self):
        process = MagicMock()
        process.stdout = io.BytesIO(b"Cell video bridge (libreoffice) at http://127.0.0.1:8765\nPairing token: local-test-token\n")
        process.poll.return_value = None
        opened = threading.Event()
        args = setup.make_parser().parse_args([])
        with patch.object(setup, "ensure_ports"), patch.object(setup.subprocess, "Popen", return_value=process) as spawn, patch.object(
                setup, "stop_bridge") as cleanup, patch.object(setup.webbrowser, "open", side_effect=lambda _: opened.set()):
            setup.launch_bridge(Path(sys.executable), Path("/office with spaces/soffice"), args, "Linux")
            self.assertTrue(opened.wait(2))
        command = spawn.call_args.args[0]
        self.assertIn("/office with spaces/soffice", command)
        self.assertIn(str(ROOT / "dist"), command)
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])
        cleanup.assert_called_once_with(process, "Linux")

    def test_failed_child_does_not_open_unrelated_listener(self):
        process = MagicMock()
        process.stdout = io.BytesIO(b"LibreOffice startup error\n")
        process.poll.return_value = 1
        process.returncode = 1
        args = setup.make_parser().parse_args([])
        with patch.object(setup, "ensure_ports"), patch.object(setup.subprocess, "Popen", return_value=process), patch.object(
                setup, "stop_bridge") as cleanup, patch.object(setup.webbrowser, "open") as browser:
            with self.assertRaisesRegex(setup.SetupError, "exited during startup"):
                setup.launch_bridge(Path(sys.executable), Path("/office/soffice"), args, "Linux")
        browser.assert_not_called()
        cleanup.assert_called_once()

    def test_stop_bridge_requests_graceful_signal_first(self):
        process = MagicMock()
        process.poll.return_value = None
        setup.stop_bridge(process, "Linux")
        process.send_signal.assert_called_once_with(signal.SIGINT)
        process.terminate.assert_not_called()
        process.wait.assert_called_once_with(timeout=10)


class EntrypointTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX terminal/process lifecycle")
    def test_ctrl_c_releases_both_ports_and_allows_immediate_restart(self):
        office_code = '''
import signal, socket, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
listener = socket.socket()
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("127.0.0.1", int(sys.argv[1])))
listener.listen()
time.sleep(30)
'''
        bridge_code = '''
import pathlib, signal, subprocess, sys, tempfile
import native.bridge as bridge
signal.signal(signal.SIGINT, signal.SIG_IGN)
class Renderer:
    mode = bridge.CalcRenderer.mode
class Owned(bridge.LibreOfficeProcess):
    def __init__(self, port):
        self.profile = pathlib.Path(tempfile.mkdtemp(prefix="profile-", dir=PROFILE_ROOT))
        self.process = subprocess.Popen([sys.executable, "-c", OFFICE_CODE, str(port)],
                                        start_new_session=True, stdout=subprocess.DEVNULL)
        print("TEST_OFFICE_PID=" + str(self.process.pid), flush=True)
bridge.launch_renderer = lambda binary, port, headless: (Renderer(), Owned(port))
bridge.main()
'''.replace("OFFICE_CODE", repr(office_code))
        runner = '''
import pathlib, signal, subprocess, sys
import setup_celluloid as setup
signal.signal(signal.SIGINT, signal.SIG_IGN)
setup.find_office = lambda *args: pathlib.Path(sys.executable)
setup.find_uno_python = lambda *args: (pathlib.Path(sys.executable), [])
original = subprocess.Popen
def spawn(command, **options):
    process = original([sys.executable, "-u", "-c", BRIDGE_CODE, *command[3:]], **options)
    print("TEST_BRIDGE_PID=" + str(process.pid), flush=True)
    return process
setup.subprocess.Popen = spawn
raise SystemExit(setup.main(sys.argv[1:]))
'''
        with tempfile.TemporaryDirectory() as directory, socket.socket() as web, socket.socket() as uno:
            web.bind(("127.0.0.1", 0))
            uno.bind(("127.0.0.1", 0))
            port, uno_port = web.getsockname()[1], uno.getsockname()[1]
            web.close()
            uno.close()
            harness = runner.replace("BRIDGE_CODE", repr(bridge_code.replace("PROFILE_ROOT", repr(directory))))
            for cycle in range(2):
                with self.subTest(restart=cycle):
                    process = subprocess.Popen([sys.executable, "-u", "-c", harness, "--no-open",
                                                "--port", str(port), "--uno-port", str(uno_port)],
                                               cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                               start_new_session=True)
                    ready, stopping = threading.Event(), threading.Event()
                    output, owned_groups = [], []

                    def read():
                        for line in process.stdout:
                            output.append(line)
                            if line.startswith(b"Open http://"):
                                ready.set()
                            if b"Stopping Celluloid..." in line:
                                stopping.set()
                            if line.startswith((b"TEST_BRIDGE_PID=", b"TEST_OFFICE_PID=")):
                                owned_groups.append(int(line.split(b"=", 1)[1]))

                    reader = threading.Thread(target=read, daemon=True)
                    reader.start()
                    try:
                        self.assertTrue(ready.wait(5), b"".join(output).decode(errors="replace"))
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}", timeout=3) as response:
                            self.assertEqual(response.status, 200)
                        deadline = time.monotonic() + 3
                        while True:
                            try:
                                socket.create_connection(("127.0.0.1", uno_port), timeout=.2).close()
                                break
                            except OSError:
                                if time.monotonic() >= deadline:
                                    self.fail("synthetic office did not bind UNO test port")
                                time.sleep(.01)
                        process.send_signal(signal.SIGINT)
                        self.assertTrue(stopping.wait(3))
                        time.sleep(.15)
                        if process.poll() is None:
                            process.send_signal(signal.SIGINT)  # Repeated Ctrl+C must not abort cleanup.
                        self.assertEqual(process.wait(timeout=8), 130, b"".join(output).decode(errors="replace"))
                        setup.ensure_ports(port, uno_port)
                        self.assertEqual(list(Path(directory).iterdir()), [], "owned profile was not removed")
                    finally:
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=5)
                        for group in owned_groups:
                            try:
                                os.killpg(group, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        reader.join(timeout=2)
                        process.stdout.close()

    @unittest.skipUnless(os.name == "posix", "POSIX bridge readiness integration")
    def test_launcher_accepts_real_bridge_banner_and_serves_app(self):
        # Keep the real bridge main, banner, HTTP server and process lifecycle.
        # Stub only native office construction; this does not claim Calc rendering.
        harness = '''
import native.bridge as bridge
class Renderer:
    mode = bridge.CalcRenderer.mode
class Owned:
    def close(self):
        print("TEST_OWNED_OFFICE_CLOSED", flush=True)
bridge.launch_renderer = lambda *args: (Renderer(), Owned())
bridge.main()
'''
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        other = port + 1 if port < 65535 else port - 1
        args = setup.make_parser().parse_args(["--port", str(port), "--uno-port", str(other)])
        actual_spawn = subprocess.Popen
        processes, responses, errors = [], [], []
        opened = threading.Event()
        output = io.StringIO()

        def spawn(command, **options):
            process = actual_spawn([sys.executable, "-u", "-c", harness, *command[3:]], **options)
            processes.append(process)

            def watchdog():
                if not opened.wait(5) and process.poll() is None:
                    process.send_signal(signal.SIGINT)

            threading.Thread(target=watchdog, daemon=True).start()
            return process

        def open_browser(url):
            try:
                with urllib.request.urlopen(url, timeout=3) as response:
                    responses.append(response.read())
            except Exception as error:
                errors.append(error)
            finally:
                opened.set()
                if processes[0].poll() is None:
                    processes[0].send_signal(signal.SIGINT)

        with contextlib.redirect_stdout(output), patch.object(setup.subprocess, "Popen", side_effect=spawn), patch.object(
                setup.webbrowser, "open", side_effect=open_browser):
            result = setup.launch_bridge(Path(sys.executable), Path("/stubbed-office/soffice"), args, "Linux")
        self.assertEqual(result, 0, output.getvalue())
        self.assertTrue(opened.is_set())
        self.assertEqual(errors, [])
        self.assertIn(b"source-video", responses[0])
        self.assertIn("Cell video bridge (libreoffice)", output.getvalue())
        self.assertIn("TEST_OWNED_OFFICE_CLOSED", output.getvalue())

    def test_universal_script_runs_from_an_unrelated_directory(self):
        with tempfile.TemporaryDirectory(prefix="celluloid outside cwd ") as directory:
            result = subprocess.run([sys.executable, str(ROOT / "setup_celluloid.py"), "--web-only", "--check"],
                                    cwd=directory, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Setup checks passed", result.stdout)

    @unittest.skipUnless(os.name == "posix" and shutil.which("sh"), "POSIX launcher")
    def test_shell_entrypoint_forwards_arguments_without_installing(self):
        with tempfile.TemporaryDirectory(prefix="celluloid shell cwd ") as directory:
            result = subprocess.run(["sh", str(ROOT / "setup.sh"), "--web-only", "--check"],
                                    cwd=directory, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Setup checks passed", result.stdout)

    @unittest.skipUnless(os.name == "posix", "POSIX SIGINT server lifecycle smoke test")
    def test_browser_only_server_serves_app_and_stops_on_interrupt(self):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        other = port + 1 if port < 65535 else port - 1
        process = subprocess.Popen([sys.executable, "-u", str(ROOT / "setup_celluloid.py"),
                                    "--web-only", "--no-open", "--port", str(port), "--uno-port", str(other)],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        ready = threading.Event()
        output = []

        def read_output():
            for line in process.stdout:
                output.append(line)
                if b"Browser studio at" in line:
                    ready.set()

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            self.assertTrue(ready.wait(8), b"".join(output).decode(errors="replace"))
            url = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(url, timeout=3) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b"source-video", response.read())
                self.assertEqual(response.headers["Permissions-Policy"], "camera=(self), microphone=(), geolocation=()")
            with urllib.request.urlopen(url + "/app.js", timeout=3) as response:
                self.assertEqual(response.headers.get_content_type(), "text/javascript")
            with self.assertRaises(urllib.error.HTTPError) as missing:
                urllib.request.urlopen(url + "/not-a-real-file.js", timeout=3)
            self.assertEqual(missing.exception.code, 404)
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            reader.join(timeout=2)
            process.stdout.close()
        self.assertEqual(process.returncode, 130)


if __name__ == "__main__":
    unittest.main()
