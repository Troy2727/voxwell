# Transcription: licenses

Transcription uses the same speech recognition model as dictation (`voxwell.features.dictation.engine`); see `../dictation/LICENSES.md`. Speaker labels (off by default) use the two small models below, downloaded on first use. Dubbing reuses them for its "label speakers" option.

| Component | Link | Code license | Weights license |
|---|---|---|---|
| faster-whisper | https://github.com/SYSTRAN/faster-whisper | MIT | n/a |
| sherpa-onnx (speaker labels; runs the two models below) | https://github.com/k2-fsa/sherpa-onnx | Apache-2.0 (`sherpa-onnx` and its `sherpa-onnx-core` native libraries) | n/a |
| pyannote segmentation 3.0, ONNX export by sherpa-onnx (`sherpa-onnx-pyannote-segmentation-3-0.tar.bz2`, SHA-256 pinned in `diarization.py`) | https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-segmentation-models (converted from https://huggingface.co/pyannote/segmentation-3.0) | MIT (the archive ships the CNRS MIT `LICENSE`) | MIT (the Hugging Face card says `license: mit`; Voxwell downloads the ungated GitHub export, never from Hugging Face) |
| 3D-Speaker CAM++ zh-en advanced (`3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx`, SHA-256 pinned in `diarization.py`) | https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models (from https://modelscope.cn/models/iic/speech_campplus_sv_zh_en_16k-common_advanced) | Apache-2.0 (https://github.com/modelscope/3D-Speaker) | Apache-2.0 (the ModelScope model card) |
| Systran/faster-whisper-small (default) | https://huggingface.co/Systran/faster-whisper-small | MIT | MIT |
