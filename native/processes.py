"""Bounded decoder subprocesses, without GUI, UNO, or third-party imports."""

from __future__ import annotations

import math
import os
import signal
import subprocess
import threading
import time


class OutputLimitError(RuntimeError):
    """A decoder exceeded its stdout budget and was stopped and reaped."""

    def __init__(self, command, limit):
        super().__init__(f"Decoder output exceeded the {limit} byte limit.")
        self.cmd = command
        self.limit = limit
        self.stdout = b""
        self.stderr = b""


def _kill_owned_process(process):
    # A dedicated POSIX process group also closes inherited pipes if a wrapper
    # executable starts a decoder child. It never includes the caller's group.
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except ProcessLookupError:
        pass
    process.wait()


def run_bounded(command, timeout, *, stdout_limit=1024 * 1024, stderr_limit=16 * 1024):
    """Run with check=True semantics and bounded byte output.

    Stdout exceeding its limit raises OutputLimitError. Stderr is drained
    continuously and retains only its tail. TimeoutExpired and CalledProcessError
    expose the same bounded stdout/stderr as a successful CompletedProcess.
    """
    for name, value in (("stdout_limit", stdout_limit), ("stderr_limit", stderr_limit)):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("timeout must be a positive finite number")

    started = time.monotonic()
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, bufsize=0,
                               start_new_session=(os.name == "posix"))
    stdout, stderr = bytearray(), bytearray()
    exceeded = threading.Event()
    finished = [threading.Event(), threading.Event()]
    read_errors = []

    def drain(stream, destination, limit, index, tail=False):
        try:
            while chunk := stream.read(64 * 1024):
                if tail:
                    if limit:
                        destination.extend(chunk)
                        if len(destination) > limit:
                            del destination[:-limit]
                else:
                    available = max(0, limit - len(destination))
                    destination.extend(chunk[:available])
                    if len(chunk) > available:
                        exceeded.set()
        except OSError as error:
            read_errors.append(error)
        finally:
            finished[index].set()

    readers = [
        threading.Thread(target=drain, args=(process.stdout, stdout, stdout_limit, 0), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, stderr, stderr_limit, 1, True), daemon=True),
    ]
    try:
        for reader in readers:
            reader.start()
        while True:
            if exceeded.is_set():
                raise OutputLimitError(command, stdout_limit)
            if read_errors:
                raise read_errors[0]
            if process.poll() is not None and all(event.is_set() for event in finished):
                break
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            interval = min(.02, remaining)
            if process.poll() is None:
                try:
                    process.wait(timeout=interval)
                except subprocess.TimeoutExpired:
                    pass
            else:
                exceeded.wait(interval)
        # The readers can discover excess stdout while process exit is observed.
        if exceeded.is_set():
            raise OutputLimitError(command, stdout_limit)
    except BaseException as error:
        _kill_owned_process(process)
        for reader in readers:
            if reader.ident is not None:
                reader.join(timeout=1)
        if isinstance(error, subprocess.TimeoutExpired):
            error.output, error.stderr = bytes(stdout), bytes(stderr)
        elif isinstance(error, OutputLimitError):
            error.stdout, error.stderr = bytes(stdout), bytes(stderr)
        raise
    finally:
        process.stdout.close()
        process.stderr.close()

    result = subprocess.CompletedProcess(command, process.returncode, bytes(stdout), bytes(stderr))
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, command, output=result.stdout,
                                            stderr=result.stderr)
    return result
