<div align="center">
  <img src="docs/logo.svg" alt="" width="88" />
  <h1>Voxwell</h1>
  <p>Voice cloning, voice design, video dubbing and dictation that run entirely on your own machine. MIT licensed.</p>
</div>

## What's inside

- **Voices**: clone a voice from a short clip, design one from a description, or pick a ready-made one from the Gallery. Saved voices work everywhere, and collections keep them organized.
- **Speech**: Stories (a script with a voice per speaker) and Audiobook (EPUB, TXT or Markdown, chapter by chapter, with resume).
- **Video**: dub videos into another language, one at a time, in a batch, or by watching a folder; optionally keep each speaker's own voice.
- **Sound effects**: describe a sound and generate it (Stable Audio Open; needs a free Hugging Face token and accepting the model's terms).
- **Text**: dictation (record and transcribe, or live: each turn is transcribed when you pause) and Transcribe (TXT, SRT or VTT, optionally with speaker labels such as "Speaker 1"), with AI clean-up of a transcript (remove filler words, fix punctuation, make it formal), plus subtitles from a script you already have: paste it, add the recording, and every word is timed against the audio.
- **Live translation**: speak in one language and hear the translation in another, turn by turn, in a saved voice or the default one.
- **Tools**: convert a recording to another voice, isolate a voice from music and noise, AI direction (describe how a line should sound; a local AI model sets the delivery), compare voices, fit audio to a length, inspect media files.
- **Effects**: add reverb, distance, background noise or stereo pan to speech (also optional when generating in Voice cloning and Stories) or to any recording, from the Effects page or `voxwell effects`.
- **Pronunciation**: teach every voice how to say names, brands and jargon; the per-language list applies to all speech, and `voxwell pronounce` manages it.
- **Projects**: everything you make, in one list.
- **Integrations**: a `voxwell` command line (speak, transcribe, edit, align, isolate, clone, design, convert, dub, translate; `--json` for scripts) with a skill that teaches Claude Code and Codex to use it, an OpenAI-compatible API at `http://127.0.0.1:8765/v1`, an MCP server for AI assistants, and optional phone calls (Twilio callers hear a greeting in your voice; off by default, and only a small separate server is ever exposed). The Integrations page shows how to connect them.

## Develop

```sh
cd backend && uv sync && uv run pytest     # backend + tests
cd app && npm install && npm run dev       # UI on http://localhost:5173
cd app && VOXWELL_DEV=1 npm run electron   # desktop shell (starts the backend)
cd backend && uv run voxwell --help        # the CLI; its commands need the backend running
```

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.11 for you), Node.js, and [ffmpeg](https://ffmpeg.org/) on your PATH for dubbing and some tools. Behind a proxy or antivirus that inspects HTTPS, set `UV_SYSTEM_CERTS=1` for the `uv` commands above (the desktop app sets it for you; the backend itself always trusts the OS certificate store). Windows and Linux get CUDA builds of PyTorch, which run on CPU when there is no NVIDIA GPU; macOS uses Apple's GPU (MPS) when available. Model weights download on first use of each feature.

## Accounts (optional)

Sign-in is off unless the app is built with a [Supabase](https://supabase.com) project; without one, the app opens straight to the dashboard. To turn it on, set the project's URL and publishable key when you run or build the UI:

```sh
cd app && VITE_SUPABASE_URL=https://<project>.supabase.co VITE_SUPABASE_PUBLISHABLE_KEY=<publishable key> npm run dev
```

In the Supabase dashboard, under Authentication > URL Configuration, add `http://localhost:5173` and `voxwell://auth/callback` (the desktop app's sign-in link) to the redirect URLs. For "Continue with Google", enable the Google provider there with your Google OAuth client. Accounts only control who can open the app: voices, audio and models stay on your machine.

Model licenses are listed per feature in `backend/voxwell/features/*/LICENSES.md`. Every model and dependency allows commercial use; `backend/tests/test_dependency_licenses.py` fails if a GPL/AGPL or non-commercial package is ever installed. For that reason voice cloning and dubbing don't support Japanese: the model's Japanese support depends on a GPL-3.0 package.
