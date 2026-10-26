# Voxwell

Voice cloning, voice design, video dubbing and dictation that run entirely on your own machine. MIT licensed.

## Develop

```sh
cd backend && uv sync && uv run pytest     # backend + tests
cd app && npm install && npm run dev       # UI on http://localhost:5173
cd app && VOXWELL_DEV=1 npm run electron   # desktop shell (starts the backend)
```

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.11 for you), Node.js, and [ffmpeg](https://ffmpeg.org/) on your PATH for dubbing. Windows and Linux get CUDA builds of PyTorch, which run on CPU when there is no NVIDIA GPU; macOS uses Apple's GPU (MPS) when available. Model weights download on first use of each feature.

Model licenses are listed per feature in `backend/voxwell/features/*/LICENSES.md`. Every model and dependency allows commercial use; `backend/tests/test_dependency_licenses.py` fails if a GPL/AGPL or non-commercial package is ever installed. For that reason voice cloning and dubbing don't support Japanese: the model's Japanese support depends on a GPL-3.0 package.
