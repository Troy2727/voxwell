"""install.sh and install.ps1, run for real against fake git, uv and ffmpeg so nothing is downloaded."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WINDOWS = sys.platform == "win32"
BIN_FOLDER = "Scripts" if WINDOWS else "bin"
EXE = ".exe" if WINDOWS else ""

# Each fake logs its arguments. `git clone` makes the folder a real clone would, `uv sync` the commands.
FAKE_UV = {
    "posix": """#!/bin/sh
echo "uv $*" >> "$FAKE_LOG"
case "$1 $2" in
  "tool dir") echo "$FAKE_BIN_DIR" ;;
  sync*) mkdir -p .venv/bin && : > .venv/bin/voxwell && : > .venv/bin/voxwell-mcp ;;
esac
""",
    "nt": """@echo off
echo uv %*>> "%FAKE_LOG%"
if "%1 %2"=="tool dir" echo %FAKE_BIN_DIR%
if "%1"=="sync" (
  mkdir .venv\\Scripts
  type nul > .venv\\Scripts\\voxwell.exe
  type nul > .venv\\Scripts\\voxwell-mcp.exe
)
""",
}
FAKE_GIT = {
    "posix": """#!/bin/sh
echo "git $*" >> "$FAKE_LOG"
if [ "$1" = clone ]; then
  for last; do :; done
  mkdir -p "$last/.git" "$last/backend"
fi
""",
    "nt": """@echo off
echo git %*>> "%FAKE_LOG%"
if "%1"=="clone" (
  mkdir "%FAKE_APP%\\.git"
  mkdir "%FAKE_APP%\\backend"
)
""",
}
FAKE_FFMPEG = {"posix": "#!/bin/sh\nexit 0\n", "nt": "@echo off\n"}


class Install:
    def __init__(self, tmp_path: Path):
        self.home = tmp_path / "home"
        self.app = self.home / "app"
        self.fakes = tmp_path / "fakes"
        self.bin = tmp_path / "bin"
        self.log = tmp_path / "log.txt"
        self.fakes.mkdir()
        self.bin.mkdir()
        self.log.touch()

    def fake(self, name: str, scripts: dict) -> None:
        path = self.fakes / (f"{name}.cmd" if WINDOWS else name)
        path.write_text(scripts[os.name], newline="\r\n" if WINDOWS else "\n")
        path.chmod(0o755)

    def run(self) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "PATH": os.pathsep.join([str(self.fakes), *self._system_path()]),
            "VOXWELL_HOME": str(self.home),
            "FAKE_LOG": str(self.log),
            "FAKE_BIN_DIR": str(self.bin),
            "FAKE_APP": str(self.app),
        }
        if WINDOWS:
            command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(REPO / "install.ps1")]
        else:
            command = ["sh", str(REPO / "install.sh")]
        return subprocess.run(command, env=env, capture_output=True, text=True, timeout=120)

    def _system_path(self) -> list[str]:
        if WINDOWS:  # System32 has PowerShell and none of the tools being faked
            root = os.environ["SystemRoot"]
            return [rf"{root}\System32", rf"{root}\System32\WindowsPowerShell\v1.0"]
        # Only the commands the script needs, so a machine's real git, uv and ffmpeg stay out of reach.
        tools = self.fakes.parent / "tools"
        tools.mkdir(exist_ok=True)
        for name in ("mkdir", "ln", "sh"):
            link = tools / name
            if not link.exists():
                link.symlink_to(shutil.which(name))
        return [str(tools)]

    def commands(self) -> list[str]:
        return [line.strip() for line in self.log.read_text().splitlines()]


@pytest.fixture
def install(tmp_path):
    return Install(tmp_path)


def fake_all(install: Install) -> None:
    install.fake("git", FAKE_GIT)
    install.fake("uv", FAKE_UV)
    install.fake("ffmpeg", FAKE_FFMPEG)


def test_fresh_install_clones_syncs_from_the_lockfile_and_adds_both_commands(install):
    fake_all(install)

    result = install.run()

    assert result.returncode == 0, result.stdout + result.stderr
    commands = install.commands()
    assert any(c.startswith("git clone") and "Troy2727/voxwell" in c for c in commands)
    assert any(c.startswith("uv sync") and "--frozen" in c and "--no-dev" in c for c in commands)
    assert any(c.startswith("uv tool update-shell") for c in commands)
    for name in ("voxwell", "voxwell-mcp"):
        assert (install.bin / (f"{name}.cmd" if WINDOWS else name)).exists()
        expected = install.app / "backend" / ".venv" / BIN_FOLDER / f"{name}{EXE}"
        shim = install.bin / (f"{name}.cmd" if WINDOWS else name)
        assert str(expected) in shim.read_text() if WINDOWS else shim.resolve() == expected.resolve()
    assert "voxwell serve" in result.stdout


def test_running_it_again_updates_instead_of_cloning(install):
    fake_all(install)
    (install.app / ".git").mkdir(parents=True)
    (install.app / "backend").mkdir()

    result = install.run()

    assert result.returncode == 0, result.stdout + result.stderr
    commands = install.commands()
    assert not any(c.startswith("git clone") for c in commands)
    assert any(c.startswith("git") and "fetch" in c for c in commands)
    assert any(c.startswith("git") and "checkout" in c for c in commands)
    assert any(c.startswith("uv sync") for c in commands)


def test_it_never_writes_over_a_folder_it_did_not_create(install):
    fake_all(install)
    install.app.mkdir(parents=True)
    keep = install.app / "notes.txt"
    keep.write_text("mine")

    result = install.run()

    assert result.returncode != 0
    assert "not a Voxwell install" in result.stdout + result.stderr
    assert keep.read_text() == "mine"
    assert install.commands() == []


def test_missing_git_stops_with_a_clear_message(install):
    install.fake("uv", FAKE_UV)
    install.fake("ffmpeg", FAKE_FFMPEG)

    result = install.run()

    assert result.returncode != 0
    assert "git" in (result.stdout + result.stderr).lower()
    assert not any(c.startswith("uv sync") for c in install.commands())


def test_missing_ffmpeg_warns_but_still_installs(install):
    install.fake("git", FAKE_GIT)
    install.fake("uv", FAKE_UV)

    result = install.run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ffmpeg" in (result.stdout + result.stderr).lower()
    assert any(c.startswith("uv sync") for c in install.commands())


def test_uv_no_modify_path_leaves_path_alone(install, monkeypatch):
    fake_all(install)
    monkeypatch.setenv("UV_NO_MODIFY_PATH", "1")

    result = install.run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert not any(c.startswith("uv tool update-shell") for c in install.commands())


@pytest.mark.skipif(not WINDOWS, reason="antivirus holding a new file is a Windows failure")
def test_windows_retries_a_sync_that_antivirus_interrupted(install):
    install.fake("git", FAKE_GIT)
    install.fake("ffmpeg", FAKE_FFMPEG)
    install.fake(
        "uv",
        {
            "nt": FAKE_UV["nt"].replace(
                'if "%1"=="sync" (',
                'if "%1"=="sync" if not exist "%FAKE_LOG%.failed" (\n  type nul > "%FAKE_LOG%.failed"\n  exit /b 2\n)\n'
                'if "%1"=="sync" (',
            )
        },
    )

    result = install.run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert len([c for c in install.commands() if c.startswith("uv sync")]) == 2
    assert (install.bin / "voxwell.cmd").exists()


def test_a_failed_sync_stops_before_adding_commands(install):
    install.fake("git", FAKE_GIT)
    install.fake("ffmpeg", FAKE_FFMPEG)
    install.fake(
        "uv",
        {
            "posix": '#!/bin/sh\necho "uv $*" >> "$FAKE_LOG"\n[ "$1" != sync ]\n',
            "nt": '@echo off\necho uv %*>> "%FAKE_LOG%"\nif "%1"=="sync" exit /b 1\n',
        },
    )

    result = install.run()

    assert result.returncode != 0
    assert not list(install.bin.iterdir())
