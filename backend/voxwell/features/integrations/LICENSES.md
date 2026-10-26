# Integrations: licenses

No models of their own: the OpenAI-compatible API (`openai_api.py`) uses voice cloning and dictation (see their `LICENSES.md`), and the MCP server (`mcp_server.py`) forwards to that API. Both are written with the standard library and FastAPI only; the Model Context Protocol is implemented directly (JSON-RPC over stdio), without an SDK.
