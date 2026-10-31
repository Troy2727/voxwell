# Models used by music

| Component | Link | Code license | Weights license |
|---|---|---|---|
| ACE-Step 1.5 (turbo DiT, VAE and Qwen3-Embedding-0.6B text encoder from `ACE-Step/Ace-Step1.5`) | https://github.com/ACE-Step/ACE-Step-1.5 , https://huggingface.co/ACE-Step/Ace-Step1.5 | MIT | MIT (model card `license: mit`; the card states generated music may be used commercially) |
| Qwen2.5-1.5B-Instruct ("Write with AI" lyrics; shared with AI direction) | https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct | Apache-2.0 (transformers) | Apache-2.0 |
| HTDemucs ("Split vocals"; the Tools voice isolation model) | see `../tools/LICENSES.md` | MIT | MIT |

Verified 2026-10-31 on the GitHub repository (`LICENSE`, `pyproject.toml` `license = {text = "MIT"}`) and the Hugging Face model API (`cardData.license: mit`).

## How it is installed

ACE-Step needs `transformers>=4.51,<4.58` and `diffusers>=0.37`, while Voxwell's environment pins `transformers==4.46.3` and `diffusers==0.36.0` for chatterbox-tts. It therefore runs in its own environment and is **not** a dependency in `pyproject.toml`:

- `runtime.py` downloads the source at commit `ca1e85fe9430179831e6bc6be790c332190a3866` into the data folder and runs `uv sync --frozen`, so the packages are exactly the ones in ACE-Step's own `uv.lock`.
- It downloads the weights at revision `19671f406d603126926c1b7e2adc169acbcade22`. The 5 Hz planning LM in that repository is not downloaded or used.
- Voxwell never ships or redistributes ACE-Step or its weights; each user's machine downloads them when they choose to install the music engine.

Checked 2026-10-31 in the installed environment's package metadata and license files; no GPL, AGPL or non-commercial package is present. Notable packages: gradio (Apache-2.0), peft (Apache-2.0), lightning (Apache-2.0), lycoris-lora (Apache-2.0), modelscope (Apache-2.0), torchao (BSD-3-Clause), vector-quantize-pytorch (MIT), nano-vllm (MIT, vendored), PyWavelets (MIT AND BSD-3-Clause), loguru (MIT), numba (BSD).

pytorch-wavelets declares "Free To Use But Restricted": its DWT code is MIT, while its DTCWT code carries the restrictions of the original DTCWT MATLAB toolbox. ACE-Step uses only the 1-D DWT (`acestep/models/common/dcw_*`), not the DTCWT.
