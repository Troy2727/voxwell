"""Integrations: what other apps need to connect (API address, MCP launch command)."""

import os
from pathlib import Path

from fastapi import APIRouter

import voxwell

router = APIRouter(tags=["integrations"])

BACKEND_DIR = Path(voxwell.__file__).resolve().parents[1]  # folder with pyproject.toml


@router.get("/status")
def status():
    return {"ready": True}


@router.get("/info")
def info():
    port = os.environ.get("VOXWELL_PORT", "8765")
    return {
        "api_base": f"http://127.0.0.1:{port}/v1",
        "mcp": {
            "command": "uv",
            "args": ["run", "--directory", str(BACKEND_DIR), "voxwell-mcp"],
            # uv trusts the OS certificate store (TLS-inspecting networks); see app/electron/main.cjs.
            "env": {"UV_SYSTEM_CERTS": "1"},
        },
    }
