"""Run the local API and Vite dev server together, tagging each output line by source."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO

_RESET = "\033[0m"


def _use_color() -> bool:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if os.name == "nt":
        os.system("")  # turns on ANSI escape handling in the Windows console
    return True


def _kill_children_with_this_process() -> None:
    """Windows: put this process in a job that ends every child when this process ends.

    Without it, killing dev.py (Task Manager, a closed terminal, a timeout) leaves uvicorn's
    server process running with the models and indexes still in memory (~12 GB of commit), and
    the next start fails to bind its port or to allocate the indexes. Children inherit the job.
    """
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", ctypes.c_uint64 * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job_object_extended_limit_information = 9
    job_object_limit_kill_on_job_close = 0x2000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    job = kernel32.CreateJobObjectW(None, None)
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = job_object_limit_kill_on_job_close
    configured = job and kernel32.SetInformationJobObject(
        job, job_object_extended_limit_information, ctypes.byref(limits), ctypes.sizeof(limits)
    )
    # The handle stays open for the life of this process; closing it is what ends the job.
    if not configured or not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        print("dev.py: could not tie the servers to this process; stop them with Ctrl+C")


def _pump(stream: IO[bytes], prefix: bytes, lock: threading.Lock) -> None:
    out = sys.stdout.buffer
    for raw in iter(stream.readline, b""):
        # Progress bars redraw with "\r"; keep only the final state of the line.
        line = raw.rstrip(b"\r\n").rsplit(b"\r", 1)[-1]
        if not line.strip():
            continue
        with lock:
            out.write(prefix + line + b"\n")
            out.flush()
    stream.close()


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    """Stop a server and everything it started (Python's launcher spawns the real one)."""
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


class Backend:
    """The API server, restarted by dev.py itself when a backend source file changes.

    uvicorn --reload is not used: on Windows it restarts its server with a Ctrl+C event,
    which reaches every process of the console, so it also stopped dev.py and Vite. And its
    restart only works when its stdout is a console, while dev.py reads it through a pipe.
    """

    def __init__(
        self, command: list[str], root: Path, env: dict[str, str], tag: bytes, lock: threading.Lock
    ) -> None:
        self._command = command
        self._root = root
        self._env = env
        self._tag = tag
        self._lock = lock
        self._swap = threading.Lock()
        self.process: subprocess.Popen[bytes] | None = None
        self._reported_exit = False

    def say(self, message: str) -> None:
        with self._lock:
            sys.stdout.buffer.write(self._tag + message.encode() + b"\n")
            sys.stdout.buffer.flush()

    def start(self) -> None:
        with self._swap:
            self.process = subprocess.Popen(
                self._command,
                cwd=self._root,
                env=self._env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
            )
            self._reported_exit = False
            threading.Thread(
                target=_pump, args=(self.process.stdout, self._tag, self._lock), daemon=True
            ).start()

    def stop(self) -> None:
        with self._swap:
            if self.process is not None:
                _kill_tree(self.process)

    def restart(self, changed: list[str]) -> None:
        shown = ", ".join(changed[:3]) + (f" (+{len(changed) - 3})" if len(changed) > 3 else "")
        self.say(f"{shown} changed: restarting the backend")
        self.stop()
        self.start()

    def report_exit(self) -> None:
        """A crash (e.g. a syntax error while editing) waits for the next change."""
        with self._swap:
            code = self.process.poll() if self.process else None
            if code is None or self._reported_exit:
                return
            self._reported_exit = True
        self.say(f"the backend stopped (exit code {code}); save a file to start it again")


def _watch_backend(backend: Backend, source: Path, root: Path, stop: threading.Event) -> None:
    try:
        from watchfiles import PythonFilter, watch
    except ImportError:
        backend.say("watchfiles is not installed: the backend will not restart on changes")
        return
    for changes in watch(source, watch_filter=PythonFilter(), stop_event=stop):
        changed = sorted({Path(path).relative_to(root).as_posix() for _, path in changes})
        backend.restart(changed)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    npm = shutil.which("npm")
    if npm is None:
        print("npm was not found on PATH", file=sys.stderr)
        return 1

    _kill_children_with_this_process()
    color = _use_color()
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    if color:
        env["FORCE_COLOR"] = "1"
    else:
        env.pop("FORCE_COLOR", None)
        env["NO_COLOR"] = "1"

    def tag(name: str, ansi: str) -> bytes:
        return (f"{ansi}{name} |{_RESET} " if color else f"{name} | ").encode()

    uvicorn = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--app-dir",
        "backend/src",
        "--port",
        "8000",
        # Access lines and server chatter drown the app's own logs; warnings still show.
        "--log-level",
        "warning",
    ]
    if color:
        uvicorn.append("--use-colors")

    lock = threading.Lock()
    backend = Backend(uvicorn, root, env, tag("api", "\033[36m"), lock)
    backend.start()
    web = subprocess.Popen(
        [npm, "--prefix", "frontend", "run", "--silent", "dev"],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    threading.Thread(
        target=_pump, args=(web.stdout, tag("web", "\033[35m"), lock), daemon=True
    ).start()
    stop_watching = threading.Event()
    threading.Thread(
        target=_watch_backend,
        args=(backend, root / "backend" / "src", root, stop_watching),
        daemon=True,
    ).start()

    try:
        while True:
            return_code = web.poll()
            if return_code is not None:
                return return_code
            backend.report_exit()
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        stop_watching.set()
        backend.stop()
        if web.poll() is None:
            web.terminate()
        try:
            web.wait(timeout=5)
        except subprocess.TimeoutExpired:
            web.kill()


if __name__ == "__main__":
    raise SystemExit(main())
