"""Which web pages may talk to the backend."""

# The renderer runs on the Vite dev server or from file:// (origin "null").
APP_ORIGINS = ("http://localhost:5173", "null")


def websocket_origin_allowed(origin: str | None) -> bool:
    """Whether a WebSocket handshake with this Origin header may connect.

    CORS does not cover WebSockets, so this is the same rule CORSMiddleware applies to fetch().
    A WebSocket handshake from a file:// page (the desktop app) can carry "file://" rather than
    "null", so both are accepted. No Origin at all means a non-browser client (the CLI, a
    script), which can reach the HTTP API too.
    """
    return origin is None or origin in APP_ORIGINS or origin == "file://"
