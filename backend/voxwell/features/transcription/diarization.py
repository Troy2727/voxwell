"""Speaker labels: work out who speaks when with sherpa-onnx's offline speaker diarization, then
label each transcript segment with the speaker whose turns overlap it most.

Two small ONNX models are downloaded on first use from the sherpa-onnx GitHub releases (no account
or token) and checked against pinned SHA-256 hashes before use; see LICENSES.md.
"""

import hashlib
import os
import shutil
import tarfile
import threading
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from voxwell.paths import data_dir, replace_file

_RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SEGMENTATION_URL = f"{_RELEASES}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
SEGMENTATION_SHA256 = "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488"  # the archive
SEGMENTATION_MEMBER = "sherpa-onnx-pyannote-segmentation-3-0/model.onnx"
EMBEDDING_URL = f"{_RELEASES}/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
EMBEDDING_SHA256 = "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"

MAX_SPEAKERS = 20
CLUSTER_THRESHOLD = 0.5  # sherpa-onnx's default: lower splits speakers more eagerly
MIN_DURATION_ON = 0.3  # seconds: shorter speech turns are dropped
MIN_DURATION_OFF = 0.5  # seconds: shorter gaps between turns of one speaker are closed

_lock = threading.Lock()


class DiarizationError(Exception):
    """A problem the user can fix or retry, with a message to show them."""


@dataclass
class Turn:
    start: float  # seconds
    end: float
    speaker: int  # sherpa-onnx's own index; only equality matters


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, sha256: str, dest: Path) -> None:
    """Fetch `url` to `dest` only if its SHA-256 matches; `dest` never holds an unchecked file."""
    part = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, part.open("wb") as out:
            shutil.copyfileobj(response, out)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise DiarizationError(f"Could not download the speaker model: {exc}")
    if _sha256(part) != sha256:
        part.unlink(missing_ok=True)
        raise DiarizationError("The downloaded speaker model is corrupted. Try again.")
    replace_file(part, dest)


def model_paths() -> tuple[Path, Path]:
    """The (segmentation, embedding) model files, downloading them (about 35 MB) the first time."""
    folder = data_dir("models", "diarization")
    segmentation, embedding = folder / "pyannote-segmentation-3-0.onnx", folder / "campplus-zh-en-advanced.onnx"
    with _lock:
        if not embedding.exists():
            _download(EMBEDDING_URL, EMBEDDING_SHA256, embedding)
        if not segmentation.exists():
            archive = folder / "segmentation.tar.bz2"
            _download(SEGMENTATION_URL, SEGMENTATION_SHA256, archive)
            try:  # read the one member by name; nothing in the archive picks a path on disk
                with tarfile.open(archive, "r:bz2") as tar, tar.extractfile(SEGMENTATION_MEMBER) as src:
                    part = segmentation.with_name(segmentation.name + ".part")
                    with part.open("wb") as out:
                        shutil.copyfileobj(src, out)
                replace_file(part, segmentation)
            except (tarfile.TarError, KeyError, OSError) as exc:
                raise DiarizationError(f"The speaker model archive could not be read: {exc}")
            finally:
                archive.unlink(missing_ok=True)
    return segmentation, embedding


def diarize(audio_path: Path, num_speakers: int = 0, on_progress: Callable[[float], None] | None = None) -> list[Turn]:
    """Who speaks when in an audio or video file. `num_speakers` 0 means find out; otherwise it is the count."""
    import sherpa_onnx
    from faster_whisper.audio import decode_audio

    if not 0 <= num_speakers <= MAX_SPEAKERS:
        raise DiarizationError(f"The number of speakers must be 0 (detect) or 1 to {MAX_SPEAKERS}.")
    segmentation, embedding = model_paths()
    threads = min(os.cpu_count() or 1, 4)
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(segmentation)),
            num_threads=threads,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(embedding), num_threads=threads),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=num_speakers or -1, threshold=CLUSTER_THRESHOLD),
        min_duration_on=MIN_DURATION_ON,
        min_duration_off=MIN_DURATION_OFF,
    )
    if not config.validate():
        raise DiarizationError("The speaker models could not be set up.")
    diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
    try:
        samples = decode_audio(str(audio_path), sampling_rate=diarizer.sample_rate)
    except Exception as exc:
        raise DiarizationError(f"Could not decode the audio: {exc}")

    def progress(done: int, total: int) -> int:
        if on_progress and total:
            on_progress(done / total)
        return 0  # keep going

    result = diarizer.process(samples, callback=progress).sort_by_start_time()
    return [Turn(r.start, r.end, r.speaker) for r in result]


def assign_speakers(spans: Sequence[tuple[float, float]], turns: Sequence[Turn]) -> list[str | None]:
    """A label ("Speaker 1", ...) for each (start, end) span: the speaker whose turns overlap it most,
    or, where none does, the speaker of the nearest turn. Speakers are numbered in order of first
    appearance. Without turns there are no labels."""
    if not turns:
        return [None] * len(spans)
    numbers: dict[int, int] = {}
    labels: list[str | None] = []
    for start, end in spans:
        overlap: dict[int, float] = {}
        for t in turns:
            shared = min(end, t.end) - max(start, t.start)
            if shared > 0:
                overlap[t.speaker] = overlap.get(t.speaker, 0.0) + shared
        if overlap:
            speaker = max(overlap, key=overlap.__getitem__)  # ties go to the first speaker found
        else:
            middle = (start + end) / 2
            speaker = min(turns, key=lambda t: max(t.start - middle, middle - t.end, 0.0)).speaker
        labels.append(f"Speaker {numbers.setdefault(speaker, len(numbers) + 1)}")
    return labels
