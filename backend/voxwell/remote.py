"""Optional dictation from your phone, over a private Tailscale connection. Off unless `voxwell serve --remote`.

The server still listens only on 127.0.0.1. `tailscale serve` receives the phone's HTTPS request,
removes any identity headers the client sent, adds the signed-in Tailscale user's, and passes the
request to this computer. So a request for the configured Host is judged here, before anything else:

- Only the owner's Tailscale account gets in.
- Other websites open on the phone can't use it: the Origin must be this page's own.
- Only the phone page and dictation are reachable, not the rest of the API.

The exact Host is required, not any *.ts.net name: a website could re-point its own name at
127.0.0.1 and set these headers itself (DNS rebinding), but it can't do that with this computer's name.

Tailscale passes on the Host it was given, so a client on the network could send "Host: 127.0.0.1"
to look local. It can't remove the headers Tailscale adds, so those mark a request as proxied, and a
proxied request for any other Host is refused, with remote access on or off.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

from starlette.responses import PlainTextResponse, Response

HOST_ENV = "VOXWELL_REMOTE_HOST"
OWNER_ENV = "VOXWELL_REMOTE_OWNER"
PAGE = Path(__file__).parent / "remote_page.html"
# The page's script and style are inline, so nothing else can run on it.
PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; media-src 'self' blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
}
# What a phone may reach. Everything else answers 404, as if it weren't there.
FORWARDED = {("GET", "/api/health"), ("POST", "/api/dictation/transcribe")}


class RemoteSetupError(Exception):
    """Remote access can't start; the message says what to do."""


def _tailscale() -> str:
    found = shutil.which("tailscale")
    if found:
        return found
    windows = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
    mac = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
    for candidate in (windows, mac):
        if candidate.exists():
            return str(candidate)
    raise RemoteSetupError("Tailscale isn't installed. Get it from https://tailscale.com/download, sign in, and try again.")


def identity_from_status(status: dict) -> tuple[str, str]:
    """(this computer's HTTPS name, the signed-in account) from `tailscale status --json`."""
    me = status.get("Self") or {}
    host = (me.get("DNSName") or "").rstrip(".").lower()
    user = ((status.get("User") or {}).get(str(me.get("UserID"))) or {}).get("LoginName") or ""
    if status.get("BackendState") != "Running" or not host or not user:
        raise RemoteSetupError("Tailscale isn't connected. Open it, sign in, and try again.")
    return host, user


def detect_identity() -> tuple[str, str]:
    try:
        done = subprocess.run([_tailscale(), "status", "--json"], capture_output=True, text=True, timeout=15, check=True)
        return identity_from_status(json.loads(done.stdout))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise RemoteSetupError("Couldn't ask Tailscale for this computer's name. Open Tailscale, sign in, and try again.") from exc


def enable(host: str, owner: str) -> None:
    os.environ[HOST_ENV] = host
    os.environ[OWNER_ENV] = owner


def instructions(host: str, owner: str, port: int) -> str:
    return (
        f"Phone dictation is on, for {owner} only.\n"
        f"1. In another terminal, run: tailscale serve --bg {port}\n"
        f"2. On your phone, with Tailscale on and signed in to {owner}, open: https://{host}\n"
        "To turn it off later: tailscale serve reset, then start Voxwell without --remote."
    )


def _host_of(scope) -> str:
    for name, value in scope["headers"]:
        if name == b"host":
            return value.decode("latin-1").rsplit(":", 1)[0].lower() if not value.startswith(b"[") else ""
    return ""


def _proxied(scope) -> bool:
    return any(name.startswith(b"tailscale-") or name == b"x-forwarded-host" for name, _ in scope["headers"])


def _header(scope, wanted: bytes) -> str | None:
    return next((value.decode("latin-1") for name, value in scope["headers"] if name == wanted), None)


class RemoteGate:
    """Decides requests for the remote Host. Every other request passes straight through."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        host = os.environ.get(HOST_ENV, "").lower()
        is_remote = bool(host) and _host_of(scope) == host
        if not is_remote and not _proxied(scope):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        if not is_remote:
            return await PlainTextResponse("Not available through a proxy.", status_code=403)(scope, receive, send)
        response = self._refusal(scope, host)
        if response is not None:
            return await response(scope, receive, send)
        # Allowed. The rest of the server only knows the local name, and this page's own Origin needs no CORS.
        headers = [(n, v) for n, v in scope["headers"] if n not in (b"host", b"origin")]
        forwarded = {**scope, "headers": [*headers, (b"host", b"127.0.0.1")]}
        return await self.app(forwarded, receive, send)

    def _refusal(self, scope, host: str) -> Response | None:
        """The response that ends this request here, or None to let it through."""
        owner = os.environ.get(OWNER_ENV, "").lower()
        if not owner or (_header(scope, b"tailscale-user-login") or "").lower() != owner:
            return PlainTextResponse("This Voxwell belongs to another Tailscale account.", status_code=403)
        origin = _header(scope, b"origin")
        if origin != f"https://{host}" and (origin is not None or scope["method"] != "GET"):
            return PlainTextResponse("Only Voxwell's own page can use this.", status_code=403)
        if (scope["method"], scope["path"]) == ("GET", "/"):
            return Response(PAGE.read_bytes(), media_type="text/html; charset=utf-8", headers=PAGE_HEADERS)
        if (scope["method"], scope["path"]) not in FORWARDED:
            return PlainTextResponse("Not found.", status_code=404)
        return None
