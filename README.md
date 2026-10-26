<div align="center">
  <img src="docs/logo.svg" alt="" width="88" />
  <h1>Voxwell</h1>
  <p>Voice cloning, voice design, video dubbing and dictation that run entirely on your own machine. MIT licensed.</p>
</div>

## What's inside

- **Voices**: clone a voice from a short clip, design one from a description, or pick a ready-made one from the Gallery. Saved voices work everywhere.
- **Speech**: Stories (a script with a voice per speaker) and Audiobook (EPUB, TXT or Markdown, chapter by chapter, with resume).
- **Video**: dub videos into another language, one at a time, in a batch, or by watching a folder.
- **Text**: dictation and Transcribe (TXT, SRT or VTT).
- **Tools**: convert a recording to another voice, compare voices, fit audio to a length, inspect media files.
- **Projects**: everything you make, in one list.
- **Integrations**: an OpenAI-compatible API at `http://127.0.0.1:8765/v1` and an MCP server for AI assistants. The Integrations page shows how to connect them.

## Develop

```sh
cd backend && uv sync && uv run pytest     # backend + tests
cd app && npm install && npm run dev       # UI on http://localhost:5173
cd app && VOXWELL_DEV=1 npm run electron   # desktop shell (starts the backend)
```

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.11 for you), Node.js, and [ffmpeg](https://ffmpeg.org/) on your PATH for dubbing and some tools. Behind a proxy or antivirus that inspects HTTPS, set `UV_SYSTEM_CERTS=1` for the `uv` commands above (the desktop app sets it for you; the backend itself always trusts the OS certificate store). Windows and Linux get CUDA builds of PyTorch, which run on CPU when there is no NVIDIA GPU; macOS uses Apple's GPU (MPS) when available. Model weights download on first use of each feature.

Model licenses are listed per feature in `backend/voxwell/features/*/LICENSES.md`. Every model and dependency allows commercial use; `backend/tests/test_dependency_licenses.py` fails if a GPL/AGPL or non-commercial package is ever installed. For that reason voice cloning and dubbing don't support Japanese: the model's Japanese support depends on a GPL-3.0 package.
