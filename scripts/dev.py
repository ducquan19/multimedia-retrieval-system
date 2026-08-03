"""Run the local API and Vite dev server together."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    npm = shutil.which("npm")
    if npm is None:
        print("npm was not found on PATH", file=sys.stderr)
        return 1

    commands = [
        [
            sys.executable,
            "-m",
            "uvicorn",
            "aic_app.main:app",
            "--app-dir",
            "backend/src",
            "--reload",
            "--port",
            "8000",
        ],
        [npm, "--prefix", "frontend", "run", "dev"],
    ]
    processes = [subprocess.Popen(command, cwd=root) for command in commands]

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
