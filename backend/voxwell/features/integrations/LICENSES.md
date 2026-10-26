# Integrations: licenses

No models of their own: the OpenAI-compatible API (`openai_api.py`) uses voice cloning and dictation (see their `LICENSES.md`), and the MCP server (`mcp_server.py`) forwards to that API. Both are written with the standard library and FastAPI only; the Model Context Protocol is implemented directly (JSON-RPC over stdio), without an SDK.

Phone calls (`phone.py`) talk to Twilio over its documented webhook protocol (TwiML and X-Twilio-Signature, implemented directly and checked against Twilio's own SDK); no Twilio library is bundled. Twilio is a paid third-party service the user signs up for separately; the feature is off by default.
