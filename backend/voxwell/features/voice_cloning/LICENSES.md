# Models used by voice_cloning

| Model | Link | Code license | Weights license |
|---|---|---|---|
| Chatterbox Multilingual V3 (Resemble AI, zero-shot cloning; 22 of its 23 languages used) | https://huggingface.co/ResembleAI/chatterbox , https://github.com/resemble-ai/chatterbox | MIT | MIT |
| Chatterbox-Turbo (Resemble AI; English speech with cue tags such as `[laugh]`) | https://huggingface.co/ResembleAI/chatterbox-turbo , https://github.com/resemble-ai/chatterbox | MIT | MIT |

Verified 2026-10-26 on the Hugging Face model card and GitHub repo. Package: `chatterbox-tts==0.1.6`. Its optional Japanese dependency `pykakasi` is GPL-3.0, so `pyproject.toml` excludes it and Japanese is not offered.

Chatterbox-Turbo verified 2026-11-13: the Hugging Face repo is public, not gated, and states the MIT license. It ships in the same `chatterbox-tts==0.1.6` package, so no new dependency is installed; Voxwell downloads its files without a Hugging Face token.

Multilingual V3 verified 2026-11-16: its checkpoint (`t3_mtl23ls_v3.safetensors`, added 2026-04-22, released 2026-06-10) is in the same public, ungated `ResembleAI/chatterbox` repo, whose card states the MIT license. It loads into the pinned `chatterbox-tts==0.1.6` with V2's other files, as upstream's own V3 loader does, so no new dependency is installed; Voxwell downloads it without a Hugging Face token.

Resemble AI retired Chatterbox in August 2026. The code and weights stay MIT, but no upstream fixes or security updates will come; the package stays pinned.

Both models watermark their output inaudibly (Resemble AI's Perth watermarker, built into the package).
