# Tools: licenses

| Component | Link | Code license | Weights license |
|---|---|---|---|
| Chatterbox VC (voice conversion; `s3gen.safetensors` + `conds.pt` from ResembleAI/chatterbox) | https://github.com/resemble-ai/chatterbox | MIT | MIT |
| Qwen2.5-1.5B-Instruct (AI direction; override with `VOXWELL_LLM_MODEL`) | https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct | Apache-2.0 (transformers) | Apache-2.0. Do not switch to Qwen2.5-3B: its weights are not Apache-2.0. |
| ffmpeg / ffprobe (Fit length, File info, AI direction pace) | https://ffmpeg.org | Not bundled; run from the user's PATH, like dubbing. | n/a |

Compare voices uses the voice cloning model (`../voice_cloning/LICENSES.md`).
