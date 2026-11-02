# Installs Voxwell's command line and MCP server on Windows. Run it again to update.
#   irm https://raw.githubusercontent.com/Troy2727/voxwell/main/install.ps1 | iex
# Everything lives in VOXWELL_HOME (default ~\.voxwell). Set VOXWELL_REF for another branch or tag,
# and UV_NO_MODIFY_PATH=1 to leave your PATH alone.

# Inside a function so a download cut short runs nothing. It throws rather than exits, because
# `exit` under iex would close the user's window.
function Install-Voxwell {
    $ErrorActionPreference = 'Stop'

    function Invoke-Checked {
        param([string]$What, [scriptblock]$Command)
        & $Command
        if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
    }

    $root = if ($env:VOXWELL_HOME) { $env:VOXWELL_HOME } else { Join-Path $HOME '.voxwell' }
    $app = Join-Path $root 'app'
    $ref = if ($env:VOXWELL_REF) { $env:VOXWELL_REF } else { 'main' }

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw 'Voxwell needs git. Install it (https://git-scm.com/downloads), then run this again.'
    }
    $isClone = Test-Path (Join-Path $app '.git')
    if ((Test-Path $app) -and -not $isClone) {
        throw "$app is not a Voxwell install, so it was left alone. Move it, or set VOXWELL_HOME to another folder."
    }
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        Write-Host 'Warning: ffmpeg was not found. Dubbing and some tools need it (winget install Gyan.FFmpeg).'
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host 'Installing uv, the tool that runs Voxwell (https://docs.astral.sh/uv/)...'
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        $uvDir = if ($env:UV_INSTALL_DIR) { $env:UV_INSTALL_DIR } else { Join-Path $HOME '.local\bin' }
        $env:Path = "$uvDir;$env:Path"
    }

    New-Item -ItemType Directory -Force -Path $root | Out-Null
    if ($isClone) {
        Write-Host "Updating Voxwell in $app..."
        Invoke-Checked 'git fetch' { git -C $app fetch --depth 1 origin $ref }
        Invoke-Checked 'git checkout' { git -C $app checkout --quiet FETCH_HEAD }
    } else {
        Write-Host "Downloading Voxwell to $app..."
        Invoke-Checked 'git clone' { git clone --depth 1 --branch $ref https://github.com/Troy2727/voxwell.git $app }
    }

    Write-Host 'Installing Python and the libraries. The first time, this downloads several GB...'
    Remove-Item Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue
    if (-not $env:UV_SYSTEM_CERTS) { $env:UV_SYSTEM_CERTS = '1' }  # antivirus and proxies that inspect HTTPS
    if (-not $env:UV_LINK_MODE) { $env:UV_LINK_MODE = 'copy' }     # hardlinks fail on OneDrive folders
    Push-Location (Join-Path $app 'backend')
    try {
        # Real-time antivirus can hold a file uv just wrote, and uv then stops with "Access is denied".
        # uv keeps what finished, so trying again carries on from there.
        for ($attempt = 1; $true; $attempt++) {
            uv sync --frozen --no-dev
            if ($LASTEXITCODE -eq 0) { break }
            if ($attempt -ge 5) { throw "uv sync failed (exit code $LASTEXITCODE). Run this installer again to continue." }
            Write-Host "uv sync stopped (exit code $LASTEXITCODE). Trying again ($($attempt + 1) of 5)..."
            Start-Sleep -Seconds 2
        }
    } finally {
        Pop-Location
    }

    $bin = (uv tool dir --bin | Out-String).Trim()
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    # Copies of uv's launchers, which hold the full path to the environment. A .cmd would not do: MCP
    # clients start the command directly, and only a shell can run one. An unchanged copy is left in
    # place, because Windows refuses to overwrite a program that is running.
    foreach ($name in 'voxwell', 'voxwell-mcp') {
        $source = Join-Path $app "backend\.venv\Scripts\$name.exe"
        $target = Join-Path $bin "$name.exe"
        if (-not (Test-Path $target) -or (Get-FileHash $source).Hash -ne (Get-FileHash $target).Hash) {
            Copy-Item $source $target -Force
        }
    }
    if (-not $env:UV_NO_MODIFY_PATH) { uv tool update-shell }

    Write-Host ''
    Write-Host 'Voxwell is installed. Open a new terminal, then:'
    Write-Host '  voxwell serve     start the server (keep it running; models download on first use)'
    Write-Host '  voxwell --help    every command, in another terminal'
    Write-Host '  voxwell-mcp       the MCP server, for your AI assistant''s settings'
    Write-Host "The commands are in $bin"
}

Install-Voxwell
