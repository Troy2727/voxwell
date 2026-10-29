# Transcription: licenses

Transcription uses the same speech recognition model as dictation (`voxwell.features.dictation.engine`); see `../dictation/LICENSES.md`. No other models. Script alignment (subtitles from a known script) adds none either: it reads word timestamps from the same Whisper model and matches words with Python's standard library (`difflib`).

| Component | Link | Code license | Weights license |
|---|---|---|---|
| faster-whisper | https://github.com/SYSTRAN/faster-whisper | MIT | n/a |
| Systran/faster-whisper-small (default) | https://huggingface.co/Systran/faster-whisper-small | MIT | MIT |
