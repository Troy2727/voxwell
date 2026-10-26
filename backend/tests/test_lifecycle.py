"""The backend must not outlive the desktop app that started it.

Electron starts `uv run voxwell`, which runs the server in a grandchild process. Killing `uv`
leaves that grandchild running on Windows, holding the port. So the app keeps the server's
stdin open, and the server stops itself when stdin closes: the OS closes it however the app
ends, including crashes.
"""

import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

SERVER = "from voxwell.main import run; run()"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(env_extra: dict, tmp_path) -> tuple[subprocess.Popen, int]:
    port = _free_port()
    env = {**os.environ, "VOXWELL_PORT": str(port), "VOXWELL_DATA_DIR": str(tmp_path), **env_extra}
    proc = subprocess.Popen([sys.executable, "-c", SERVER], stdin=subprocess.PIPE, env=env)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
            return proc, port
        except OSError:
            if proc.poll() is not None:
                pytest.fail(f"server exited early with code {proc.returncode}")
            time.sleep(0.3)
    proc.kill()
    pytest.fail("server did not start")


def test_server_stops_when_the_app_closes_its_stdin(tmp_path):
    proc, _ = _start({"VOXWELL_EXIT_WITH_PARENT": "1"}, tmp_path)
    proc.stdin.close()  # what the OS does when Electron quits or crashes
    try:
        assert proc.wait(timeout=20) == 0
    finally:
        proc.kill()


def test_server_ignores_stdin_when_started_by_hand(tmp_path):
    # `uv run voxwell` in a terminal: closing stdin (e.g. Ctrl+Z/Ctrl+D) must not stop it.
    proc, port = _start({"VOXWELL_EXIT_WITH_PARENT": ""}, tmp_path)
    try:
        proc.stdin.close()
        time.sleep(2)
        assert proc.poll() is None
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2)
    finally:
        proc.kill()
        proc.wait()
