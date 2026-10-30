import bz2
import hashlib
import io
import tarfile
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.features.dictation import engine
from voxwell.features.dictation.engine import Segment, Transcript
from voxwell.features.dubbing import ffmpeg, jobs as dubbing_jobs
from voxwell.features.dubbing import translate as translator
from voxwell.features.transcription import diarization, jobs
from voxwell.features.transcription.diarization import DiarizationError, Turn, assign_speakers
from voxwell.features.voice_cloning import engine as cloning_engine
from voxwell.main import app

client = TestClient(app)

SEGMENTS = [Segment(0.0, 1.5, "Hello there."), Segment(2.0, 3.25, "Welcome to Voxwell."), Segment(4.0, 5.0, "Thanks.")]
TURNS = [Turn(0.0, 1.8, 7), Turn(1.8, 3.4, 3), Turn(3.9, 5.0, 7)]  # sherpa's own speaker numbers


# --- assigning labels ----------------------------------------------------------------------


def test_each_span_takes_the_speaker_with_the_most_overlap():
    turns = [Turn(0.0, 2.0, 0), Turn(2.0, 6.0, 1)]
    assert assign_speakers([(0.0, 1.0), (1.5, 4.0), (5.0, 6.0)], turns) == ["Speaker 1", "Speaker 2", "Speaker 2"]


def test_overlap_is_summed_over_a_speakers_turns():
    turns = [Turn(0.0, 1.0, 0), Turn(1.0, 3.0, 1), Turn(3.0, 4.0, 0), Turn(4.0, 5.0, 0)]
    assert assign_speakers([(0.5, 4.8)], turns) == ["Speaker 1"]  # speaker 0 holds 0.5 + 1.0 + 0.8 of it


def test_speakers_are_numbered_by_first_appearance_not_by_the_models_index():
    turns = [Turn(0.0, 1.0, 5), Turn(1.0, 2.0, 2), Turn(2.0, 3.0, 5)]
    assert assign_speakers([(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)], turns) == ["Speaker 1", "Speaker 2", "Speaker 1"]
    assert assign_speakers([(1.0, 2.0), (0.0, 1.0)], turns) == ["Speaker 1", "Speaker 2"]


def test_a_span_in_silence_takes_the_nearest_turn():
    turns = [Turn(0.0, 1.0, 0), Turn(10.0, 11.0, 1)]
    assert assign_speakers([(2.0, 3.0), (8.0, 9.0)], turns) == ["Speaker 1", "Speaker 2"]


def test_an_exact_tie_goes_to_the_first_speaker():
    assert assign_speakers([(0.0, 2.0)], [Turn(0.0, 1.0, 4), Turn(1.0, 2.0, 9)]) == ["Speaker 1"]


def test_no_turns_means_no_labels():
    assert assign_speakers([(0.0, 1.0), (1.0, 2.0)], []) == [None, None]
    assert assign_speakers([], [Turn(0.0, 1.0, 0)]) == []


# --- transcription jobs --------------------------------------------------------------------


@pytest.fixture
def fake(monkeypatch):
    calls = {"diarize": []}

    def transcribe(audio_path, language=None, on_progress=None):
        return Transcript("Hello there. Welcome to Voxwell. Thanks.", "en", SEGMENTS)

    def diarize(path, num_speakers=0, on_progress=None):
        calls["diarize"].append((path.suffix, num_speakers))
        if on_progress:
            on_progress(1.0)
        return TURNS

    monkeypatch.setattr(engine, "transcribe", transcribe)
    monkeypatch.setattr(diarization, "diarize", diarize)
    monkeypatch.setattr(jobs, "start", jobs._work)  # run synchronously
    return calls


def post(speakers=None, num_speakers=None, name="Interview.mp3"):
    data = {}
    if speakers is not None:
        data["speakers"] = str(speakers).lower()
    if num_speakers is not None:
        data["num_speakers"] = str(num_speakers)
    return client.post("/api/transcription/jobs", files={"file": (name, b"audio", "audio/mpeg")}, data=data)


def done(**kw):
    r = post(**kw)
    assert r.status_code == 200
    return client.get(f"/api/transcription/jobs/{r.json()['id']}").json()


def export(job, fmt):
    r = client.get(f"/api/transcription/jobs/{job['id']}/export/{fmt}")
    assert r.status_code == 200
    return r.text


def test_labels_are_off_by_default_and_exports_are_unchanged(fake):
    job = done()
    assert fake["diarize"] == []
    assert all("speaker" not in s for s in job["transcript"]["segments"]) and "speakers_error" not in job["transcript"]
    assert export(job, "txt") == "Hello there. Welcome to Voxwell. Thanks.\n"
    assert export(job, "srt").startswith("1\n00:00:00,000 --> 00:00:01,500\nHello there.\n")
    assert export(job, "vtt") == (
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nHello there.\n\n"
        "00:00:02.000 --> 00:00:03.250\nWelcome to Voxwell.\n\n00:00:04.000 --> 00:00:05.000\nThanks.\n"
    )
    assert done(speakers=False)["transcript"]["segments"] == job["transcript"]["segments"]


def test_labelled_transcript_and_exports(fake):
    job = done(speakers=True)
    assert job["state"] == "done" and job["percent"] == 100
    assert [s["speaker"] for s in job["transcript"]["segments"]] == ["Speaker 1", "Speaker 2", "Speaker 1"]
    assert job["transcript"]["text"] == "Hello there. Welcome to Voxwell. Thanks."
    assert fake["diarize"] == [(".mp3", 0)]  # the upload, with the speaker count left to detect
    assert export(job, "txt") == "Speaker 1: Hello there.\n\nSpeaker 2: Welcome to Voxwell.\n\nSpeaker 1: Thanks.\n"
    assert "1\n00:00:00,000 --> 00:00:01,500\nSpeaker 1: Hello there.\n" in export(job, "srt")
    vtt = export(job, "vtt")
    assert "00:00:00.000 --> 00:00:01.500\n<v Speaker 1>Hello there.\n" in vtt
    assert "00:00:02.000 --> 00:00:03.250\n<v Speaker 2>Welcome to Voxwell.\n" in vtt


def test_consecutive_segments_of_one_speaker_share_a_text_paragraph(fake, monkeypatch):
    monkeypatch.setattr(diarization, "diarize", lambda *a, **k: [Turn(0.0, 6.0, 0)])
    assert export(done(speakers=True), "txt") == "Speaker 1: Hello there. Welcome to Voxwell. Thanks.\n"


def test_num_speakers_is_passed_on_and_only_used_when_labelling(fake):
    done(speakers=True, num_speakers=2)
    assert fake["diarize"] == [(".mp3", 2)]
    assert jobs.get(client.get("/api/transcription/jobs").json()[0]["id"]).num_speakers == 2
    done(speakers=False, num_speakers=2)
    assert len(fake["diarize"]) == 1


@pytest.mark.parametrize("n", ["-1", "21", "many"])
def test_bad_speaker_count(fake, n):
    assert post(speakers=True, num_speakers=n).status_code == 422


def test_speaker_failure_keeps_the_transcript(fake, monkeypatch):
    def boom(*a, **k):
        raise DiarizationError("Could not download the speaker model: offline")

    monkeypatch.setattr(diarization, "diarize", boom)
    job = done(speakers=True)
    assert job["state"] == "done" and job["transcript"]["text"].startswith("Hello there.")
    assert job["transcript"]["speakers_error"] == "Speaker labels failed: Could not download the speaker model: offline"
    assert all("speaker" not in s for s in job["transcript"]["segments"])
    assert export(job, "txt") == "Hello there. Welcome to Voxwell. Thanks.\n"


def test_no_speakers_found_is_reported(fake, monkeypatch):
    monkeypatch.setattr(diarization, "diarize", lambda *a, **k: [])
    job = done(speakers=True)
    assert job["state"] == "done" and job["transcript"]["speakers_error"] == "No speakers were found in the file."


def test_setting_survives_a_restart(fake, monkeypatch):
    jid = done(speakers=True, num_speakers=3)["id"]
    monkeypatch.setattr(jobs, "_jobs", {})
    job = jobs.get(jid)
    assert (job.speakers, job.num_speakers) == (True, 3)


# --- the speaker models: download, pinning, wiring -----------------------------------------


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def archive(member=diarization.SEGMENTATION_MEMBER, payload=b"segmentation weights") -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        info = tarfile.TarInfo(member)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return bz2.compress(raw.getvalue())


def serve(monkeypatch, files: dict[str, bytes]):
    """Make urlopen return `files` by URL, and pin their hashes."""
    monkeypatch.setattr(diarization.urllib.request, "urlopen", lambda url, timeout=0: FakeResponse(files[url]))
    monkeypatch.setattr(diarization, "SEGMENTATION_SHA256", hashlib.sha256(files[diarization.SEGMENTATION_URL]).hexdigest())
    monkeypatch.setattr(diarization, "EMBEDDING_SHA256", hashlib.sha256(files[diarization.EMBEDDING_URL]).hexdigest())


def test_models_download_once_and_are_verified(monkeypatch, isolated_data_dir):
    files = {diarization.SEGMENTATION_URL: archive(), diarization.EMBEDDING_URL: b"embedding weights"}
    serve(monkeypatch, files)
    segmentation, embedding = diarization.model_paths()
    assert segmentation.read_bytes() == b"segmentation weights" and embedding.read_bytes() == b"embedding weights"
    assert sorted(p.name for p in segmentation.parent.iterdir()) == sorted([segmentation.name, embedding.name])  # no leftovers
    monkeypatch.setattr(diarization.urllib.request, "urlopen", lambda *a, **k: pytest.fail("downloaded twice"))
    assert diarization.model_paths() == (segmentation, embedding)


def test_a_model_with_the_wrong_hash_is_rejected_and_removed(monkeypatch, isolated_data_dir):
    files = {diarization.SEGMENTATION_URL: archive(), diarization.EMBEDDING_URL: b"tampered"}
    serve(monkeypatch, files)
    monkeypatch.setattr(diarization, "EMBEDDING_SHA256", "0" * 64)
    with pytest.raises(DiarizationError, match="corrupted"):
        diarization.model_paths()
    assert list((isolated_data_dir / "models" / "diarization").iterdir()) == []


def test_an_archive_without_the_model_is_an_error(monkeypatch, isolated_data_dir):
    files = {diarization.SEGMENTATION_URL: archive(member="elsewhere/model.onnx"), diarization.EMBEDDING_URL: b"e"}
    serve(monkeypatch, files)
    with pytest.raises(DiarizationError, match="archive could not be read"):
        diarization.model_paths()
    assert not (isolated_data_dir / "models" / "diarization" / "pyannote-segmentation-3-0.onnx").exists()


def test_download_failure_is_a_clear_error(monkeypatch, isolated_data_dir):
    def offline(url, timeout=0):
        raise OSError("no network")

    monkeypatch.setattr(diarization.urllib.request, "urlopen", offline)
    with pytest.raises(DiarizationError, match="Could not download the speaker model: no network"):
        diarization.model_paths()


def test_speaker_count_is_validated_before_any_download(monkeypatch):
    monkeypatch.setattr(diarization, "model_paths", lambda: pytest.fail("should not download"))
    with pytest.raises(DiarizationError, match="between|must be"):
        diarization.diarize(Path("x.wav"), 99)


# --- dubbing -------------------------------------------------------------------------------


def wav_bytes(seconds: float = 1.0, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture
def dub(monkeypatch):
    calls = {"synth": [], "ffmpeg": [], "diarize": []}

    def fake_ffmpeg(args):
        calls["ffmpeg"].append(args)
        out = Path(args[-1])
        out.write_bytes(wav_bytes() if out.suffix == ".wav" else b"video")

    def diarize(path, num_speakers=0, on_progress=None):
        calls["diarize"].append((path.name, num_speakers))
        return [Turn(0.0, 2.5, 0), Turn(2.5, 6.0, 1)]

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(engine, "transcribe", lambda p, language=None: Transcript("hola mundo adios", "es", [Segment(0.0, 2.0, "hola mundo"), Segment(3.0, 5.0, "adios")]))
    monkeypatch.setattr(translator, "translate", lambda texts, s, t: [f"[{t}] {x}" for x in texts])
    monkeypatch.setattr(cloning_engine, "synthesize", lambda text, language, reference_audio=None: calls["synth"].append((text, reference_audio)) or wav_bytes())
    monkeypatch.setattr(diarization, "diarize", diarize)
    monkeypatch.setattr(dubbing_jobs, "start", dubbing_jobs._work)
    return calls


def dub_post(voice="original", **form):
    return client.post("/api/dubbing/jobs", files={"file": ("clip.mp4", b"video", "video/mp4")}, data={"target_language": "en", "voice": voice, **form})


def subtitles(response):
    return client.get(f"/api/dubbing/jobs/{response.json()['id']}/subtitles").text


def test_dubbing_is_unchanged_without_speakers(dub):
    r = dub_post()
    assert r.status_code == 200 and dub["diarize"] == []
    assert [Path(ref).name for _, ref in dub["synth"]] == ["reference.wav", "reference.wav"]
    assert "[en] adios" in subtitles(r) and "Speaker" not in subtitles(r)


def test_each_speaker_keeps_their_own_voice(dub):
    r = dub_post(speakers="true", num_speakers="2")
    assert r.status_code == 200 and dub["diarize"] == [("source.wav", 2)]
    assert [Path(ref).name for _, ref in dub["synth"]] == ["reference.wav", "reference1.wav"]
    srt = subtitles(r)
    assert "Speaker 1: [en] hola mundo" in srt and "Speaker 2: [en] adios" in srt


def test_a_saved_voice_speaks_every_speaker(dub):
    voice = voices.save_voice("Ann", wav_bytes(1.0), "upload")
    r = dub_post(voice=voice.id, speakers="true")
    assert {ref for _, ref in dub["synth"]} == {voices.voice_audio_path(voice.id)}
    assert "Speaker 2: [en] adios" in subtitles(r)  # still labelled


def test_dub_speaker_failure_is_a_job_error(dub, monkeypatch):
    def boom(*a, **k):
        raise DiarizationError("Could not download the speaker model: offline")

    monkeypatch.setattr(diarization, "diarize", boom)
    jid = dub_post(speakers="true").json()["id"]
    job = client.get(f"/api/dubbing/jobs/{jid}").json()
    assert job["state"] == "error" and job["error"] == "Could not download the speaker model: offline"


def test_dub_speaker_setting_is_validated_and_persisted(dub, monkeypatch):
    assert dub_post(speakers="true", num_speakers="50").status_code == 422
    jid = dub_post(speakers="true", num_speakers="3").json()["id"]
    monkeypatch.setattr(dubbing_jobs, "_jobs", {})
    job = dubbing_jobs.get(jid)
    assert (job.speakers, job.num_speakers) == (True, 3)
