# Contributing

## Layout

- `backend/voxwell/features/<feature>/`: one folder per feature (`voice_cloning`, `voice_design`, `sound`, `voices`, `voice_collections`, `gallery`, `stories`, `audiobook`, `dubbing`, `batch`, `dictation`, `transcription`, `tools`, `integrations`, `projects`) with its FastAPI `router.py`, mounted at `/api/<feature>/`. `projects` owns no files: it lists, renames and deletes through each feature's own store (`voice_cloning/history.py`, `stories/jobs.py`, `audiobook/books.py`, `dubbing/jobs.py`, `transcription/jobs.py`). A feature can run a background task while the server is up via `Feature.background` (the watch folder uses it).
- `app/src/features/<feature>/Page.tsx`: the matching React page.
- `app/src/components/`: Voxwell's shared page pieces (`Page`, `Section`, `Field`, `FileDrop`, `AudioResult`, `VoiceSelect`, `JobProgress`, `ConfirmButton`).
- `app/src/components/ui/`: UI components copied from shadcn/ui and ElevenLabs UI (both MIT); see its `LICENSES.md`.
- `app/src/auth/` and `app/src/lib/auth.ts`: optional sign-in (Supabase) in front of the dashboard; see the README's Accounts section.
- `backend/voxwell/cli.py`: the `voxwell` command. No arguments (or `serve`) starts the server, which is what the desktop app runs; every other command is a stdlib-only client of the running server's HTTP API. The MCP server (`features/integrations/mcp_server.py`) exposes the same commands as tools by calling them. Give new user-facing features a CLI command and a matching MCP tool, and mention anything `--help` cannot say in `skills/voxwell/SKILL.md` (the skill the Integrations page installs for Claude Code and Codex).
- `app/electron/`: the desktop shell; it starts the backend and receives `voxwell://auth/callback` sign-in links.

## Licensing

Voxwell is MIT. Only add code you wrote yourself or code under a permissive license (MIT, Apache-2.0, BSD). Never copy from GPL/AGPL projects.

Models must allow commercial use for both **code and weights** (MIT, Apache-2.0, BSD, CC-BY-4.0). No CC-BY-NC, "non-commercial" or "research only" licenses. The single owner-approved exception is Stable Audio Open (Stability AI Community License, free below US$1M annual revenue) for the `sound` feature; see `backend/voxwell/features/sound/LICENSES.md`. Record each model in its feature's `LICENSES.md`. `backend/tests/test_dependency_licenses.py` fails if a GPL/AGPL or non-commercial package gets installed.

## Backend

- Add dependencies to `backend/pyproject.toml`, then run `uv lock`.
- Import heavy libraries (torch, model packages) inside functions, so the app starts fast and tests run without loading models.
- Load models lazily and cache them per process; pick CUDA, then Apple MPS, then CPU.
- Store files under `voxwell.paths.data_dir("<feature>")`. Never use a client-supplied filename as a path.
- Keep the shared engine signatures stable: `voice_cloning.engine.synthesize()` and `dictation.engine.transcribe()` are used by dubbing.
- Return clear error messages with `HTTPException`, never stack traces.

## Tests

- Put tests in `backend/tests/features/test_<feature>.py`, using `TestClient` against `voxwell.main.app`.
- Mock the model in feature tests; they must not download weights or need a GPU.
- `backend/tests/test_model_api_contracts.py` checks engine calls against the installed libraries' real signatures. Extend it when you call a new model API.

## Frontend

- React function components in TypeScript. Talk to the backend through `app/src/api.ts`.
- Build pages from `app/src/components` and `app/src/components/ui`, styled with Tailwind classes. Use the theme colors (`bg-primary`, `text-muted-foreground`, …) defined in `app/src/styles.css`, never raw color values, so dark and light mode both work. Show loading, error and empty states.
- To add a shadcn component, run `npx shadcn@latest add <name>` in `app/`. The CLI imports `cn` from the `cn` package; change that to `@/lib/utils` and uninstall `cn`. List the file in `app/src/components/ui/LICENSES.md`, and mark any change you make to a copied file with a `Voxwell:` comment.

## Cross-platform

Default behavior must be the same on Windows, macOS and Linux. Anything platform-only goes behind an opt-in setting.

## Before opening a PR

```sh
cd backend && uv run pytest
cd app && npm run typecheck && npm run build
```
