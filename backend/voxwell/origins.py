"""Which web pages may talk to the backend."""

# The renderer runs on the Vite dev server or from app://voxwell (the packaged desktop app); the
# hosted web build at voxwell.vercel.app talks to the backend on the visitor's own computer.
# Never "null": that is the origin of file:// pages, but also of sandboxed iframes on any website.
APP_ORIGINS = ("http://localhost:5173", "app://voxwell", "https://voxwell.vercel.app")

# The names the backend answers to. Any other Host means a website whose name was re-pointed at
# 127.0.0.1 (DNS rebinding), which would otherwise count as the same origin as this API.
APP_HOSTS = ("127.0.0.1", "localhost")


def websocket_origin_allowed(origin: str | None) -> bool:
    """Whether a WebSocket handshake with this Origin header may connect.

    CORS does not cover WebSockets, so this is the same rule CORSMiddleware applies to fetch().
    No Origin at all means a non-browser client (the CLI, a script), which can reach the HTTP
    API too.
    """
    return origin is None or origin in APP_ORIGINS
