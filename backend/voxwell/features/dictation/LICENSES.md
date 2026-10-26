# Dictation licenses

| Component | Link | Code license | Weights license |
|---|---|---|---|
| faster-whisper (CTranslate2 Whisper runtime) | https://github.com/SYSTRAN/faster-whisper | MIT | n/a |
| Systran/faster-whisper-small (default; size set by `VOXWELL_WHISPER_MODEL`) | https://huggingface.co/Systran/faster-whisper-small | MIT | MIT (CTranslate2 conversion of OpenAI Whisper, MIT) |

Other `Systran/faster-whisper-*` sizes (tiny, base, medium, large-v3) carry the same MIT license; verify the model card before pointing the env var at a non-Systran repo.
