"""Real child-process checks for bounded output and decoder cleanup."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from native.processes import OutputLimitError, run_bounded


class BoundedProcessTests(unittest.TestCase):
    def command(self, script):
        return [sys.executable, "-c", script]

    def test_normal_json_and_stderr_tail(self):
        result = run_bounded(self.command(
            "import sys; sys.stderr.buffer.write(b'x'*131072+b'END'); print('{\"width\":48}')"),
            5, stderr_limit=32)
        self.assertEqual(json.loads(result.stdout), {"width": 48})
        self.assertEqual(result.stderr, b"x" * 29 + b"END")
        self.assertEqual(result.returncode, 0)

    def test_output_limit_drains_both_pipes_and_reaps_decoder(self):
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "pid"
            script = (f"import os,sys,time; open({str(pid_file)!r},'w').write(str(os.getpid())); "
                      "sys.stderr.buffer.write(b'e'*131072); sys.stderr.flush(); "
                      "sys.stdout.buffer.write(b'o'*131072); sys.stdout.flush(); time.sleep(30)")
            with self.assertRaises(OutputLimitError) as caught:
                run_bounded(self.command(script), 5, stdout_limit=4096, stderr_limit=2048)
            self.assertEqual(caught.exception.stdout, b"o" * 4096)
            self.assertEqual(caught.exception.stderr, b"e" * 2048)
            self.assertLess(time.monotonic() - started, 3)
            if os.name == "posix":
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(pid_file.read_text()), 0)

    def test_nonzero_exit_retains_bounded_diagnostics(self):
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            run_bounded(self.command("import sys; print('probe'); sys.stderr.write('x'*10000+'bad'); sys.exit(7)"),
                        5, stderr_limit=12)
        self.assertEqual(caught.exception.returncode, 7)
        self.assertEqual(caught.exception.stdout, b"probe\n")
        self.assertEqual(caught.exception.stderr, b"x" * 9 + b"bad")

    def test_timeout_kills_and_reaps_decoder(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "pid"
            script = (f"import os,sys,time; open({str(pid_file)!r},'w').write(str(os.getpid())); "
                      "print('ready',flush=True); sys.stderr.write('diagnostic'); sys.stderr.flush(); time.sleep(30)")
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                run_bounded(self.command(script), .3, stderr_limit=5)
            self.assertLess(time.monotonic() - started, 3)
            self.assertEqual(caught.exception.stdout, b"ready\n")
            self.assertEqual(caught.exception.stderr, b"ostic")
            if os.name == "posix":
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(pid_file.read_text()), 0)

    def test_exact_stdout_limit_is_allowed_and_zero_limits_are_supported(self):
        self.assertEqual(run_bounded(self.command("print('123',end='')"), 5, stdout_limit=3).stdout, b"123")
        result = run_bounded(self.command("import sys;sys.stderr.write('discard')"), 5,
                             stdout_limit=0, stderr_limit=0)
        self.assertEqual((result.stdout, result.stderr), (b"", b""))


if __name__ == "__main__":
    unittest.main()
