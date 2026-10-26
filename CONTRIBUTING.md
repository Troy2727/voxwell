# Contributing

## Layout

- `backend/voxwell/features/<feature>/`: one folder per feature (`voice_cloning`, `voice_design`, `voices`, `gallery`, `stories`, `audiobook`, `dubbing`, `batch`, `dictation`, `transcription`, `tools`, `integrations`, `projects`) with its FastAPI `router.py`, mounted at `/api/<feature>/`. `projects` owns no files: it lists, renames and deletes through each feature's own store (`voice_cloning/history.py`, `stories/jobs.py`, `audiobook/books.py`, `dubbing/jobs.py`, `transcription/jobs.py`). A feature can run a background task while the server is up via `Feature.background` (the watch folder uses it).
- `app/src/features/<feature>/Page.tsx`: the matching React page.
- `app/electron/`: the desktop shell; it starts the backend.

## Licensing

Voxwell is MIT. Only add code you wrote yourself or code under a permissive license (MIT, Apache-2.0, BSD). Never copy from GPL/AGPL projects.

Models must allow commercial use for both **code and weights** (MIT, Apache-2.0, BSD, CC-BY-4.0). No CC-BY-NC, "non-commercial" or "research only" licenses. Record each model in its feature's `LICENSES.md`. `backend/tests/test_dependency_licenses.py` fails if a GPL/AGPL or non-commercial package gets installed.

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
- Use the shared classes in `app/src/styles.css`. Show loading, error and empty states.

## Cross-platform

Default behavior must be the same on Windows, macOS and Linux. Anything platform-only goes behind an opt-in setting.

## Before opening a PR

```sh
cd backend && uv run pytest
cd app && npm run typecheck && npm run build
```
