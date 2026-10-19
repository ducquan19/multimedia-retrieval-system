"""Run the local API and Vite dev server together, tagging each output line by source."""

from __future__ import annotations

import os
import shutil
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

    uvicorn = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--app-dir",
        "backend/src",
        "--reload",
        "--port",
        "8000",
        # Access lines and reloader chatter drown the app's own logs; warnings still show.
        "--log-level",
        "warning",
    ]
    if color:
        uvicorn.append("--use-colors")
    commands = [
        ("api", "\033[36m", uvicorn),
        ("web", "\033[35m", [npm, "--prefix", "frontend", "run", "--silent", "dev"]),
    ]

    lock = threading.Lock()
    processes: list[subprocess.Popen[bytes]] = []
    for name, ansi, command in commands:
        process = subprocess.Popen(
            command, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        tag = f"{ansi}{name} |{_RESET} " if color else f"{name} | "
        threading.Thread(
            target=_pump, args=(process.stdout, tag.encode(), lock), daemon=True
        ).start()
        processes.append(process)

    try:
        while True:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    return return_code
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
