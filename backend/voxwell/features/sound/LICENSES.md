# Models used by sound

| Model | Link | Code license | Weights license |
|---|---|---|---|
| Stable Audio Open 1.0 (Stability AI, text-to-sound) | https://huggingface.co/stabilityai/stable-audio-open-1.0 | Apache-2.0 (diffusers pipeline that runs it) | **Stability AI Community License** |

## The one approved exception to the license rule

Every other model in Voxwell has MIT, Apache-2.0, BSD or CC-BY-4.0 weights. Stable Audio Open does not: its weights are under the [Stability AI Community License](https://stability.ai/community-license-agreement). It is free to use, including commercially, for individuals and organizations with under US$1M in annual revenue; larger organizations need an enterprise license from Stability AI. The repository owner approved this as the **single exception** to the commercial-use rule in `CONTRIBUTING.md`. Do not add other models under non-permissive licenses.

The weights are gated on Hugging Face: each user must accept the terms at the model page and provide a Hugging Face access token (the `HF_TOKEN` environment variable, or saved on the Sound page). Voxwell never ships or redistributes the weights.

Packages added for this feature: `diffusers` (Apache-2.0) and `torchsde` (Apache-2.0, which pulls in `trampoline`, MIT). `diffusers` is pinned to 0.36.0 with a uv override because `chatterbox-tts` pins an older release; see `pyproject.toml`.
