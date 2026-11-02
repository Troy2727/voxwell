#!/bin/sh
# Installs Voxwell's command line and MCP server on macOS or Linux. Run it again to update.
#   curl -LsSf https://raw.githubusercontent.com/Troy2727/voxwell/main/install.sh | sh
# Everything lives in VOXWELL_HOME (default ~/.voxwell). Set VOXWELL_REF for another branch or tag,
# and UV_NO_MODIFY_PATH=1 to leave your shell's PATH alone.

# Inside a function so a download cut short runs nothing.
main() {
  set -eu

  home="${VOXWELL_HOME:-$HOME/.voxwell}"
  app="$home/app"
  ref="${VOXWELL_REF:-main}"

  if ! command -v git >/dev/null 2>&1; then
    echo "Voxwell needs git. Install it (https://git-scm.com/downloads), then run this again." >&2
    exit 1
  fi
  if [ -e "$app" ] && [ ! -d "$app/.git" ]; then
    echo "$app is not a Voxwell install, so it was left alone. Move it, or set VOXWELL_HOME to another folder." >&2
    exit 1
  fi
  if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "Warning: ffmpeg was not found. Dubbing and some tools need it (brew install ffmpeg, or apt install ffmpeg)."
  fi
  if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv, the tool that runs Voxwell (https://docs.astral.sh/uv/)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="${UV_INSTALL_DIR:-$HOME/.local/bin}:$PATH"
    export PATH
  fi

  mkdir -p "$home"
  if [ -d "$app/.git" ]; then
    echo "Updating Voxwell in $app..."
    git -C "$app" fetch --depth 1 origin "$ref"
    git -C "$app" checkout --quiet FETCH_HEAD
  else
    echo "Downloading Voxwell to $app..."
    git clone --depth 1 --branch "$ref" https://github.com/Troy2727/voxwell.git "$app"
  fi

  echo "Installing Python and the libraries. The first time, this downloads several GB..."
  unset UV_PROJECT_ENVIRONMENT
  (cd "$app/backend" && UV_SYSTEM_CERTS="${UV_SYSTEM_CERTS:-1}" uv sync --frozen --no-dev)

  bin="$(uv tool dir --bin)"
  mkdir -p "$bin"
  ln -sf "$app/backend/.venv/bin/voxwell" "$bin/voxwell"
  ln -sf "$app/backend/.venv/bin/voxwell-mcp" "$bin/voxwell-mcp"
  if [ -z "${UV_NO_MODIFY_PATH:-}" ]; then
    uv tool update-shell || true
  fi

  echo
  echo "Voxwell is installed. Open a new terminal, then:"
  echo "  voxwell serve     start the server (keep it running; models download on first use)"
  echo "  voxwell --help    every command, in another terminal"
  echo "  voxwell-mcp       the MCP server, for your AI assistant's settings"
  echo "The commands are in $bin"
}

main "$@"
