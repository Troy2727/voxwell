import io
import shutil
import subprocess
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.features.dictation import engine as dictation_engine
from voxwell.features.dictation.engine import Segment, Transcript
from voxwell.features.dubbing import ffmpeg, fitting, jobs, pipeline
from voxwell.features.dubbing import translate as translator
from voxwell.features.voice_cloning import engine as cloning_engine
from voxwell.main import app

client = TestClient(app)


def wav_bytes(seconds: float, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture
def mocked(monkeypatch):
    calls = {"synth": [], "ffmpeg": []}

    def fake_ffmpeg(args):
        calls["ffmpeg"].append(args)
        out = Path(args[-1])
        # Normalizing/extracting writes 1 s of audio; the mux writes opaque bytes.
        out.write_bytes(wav_bytes(1.0) if out.suffix == ".wav" else b"video")

    def fake_transcribe(audio_path, language=None):
        return Transcript("hola mundo adios", "es", [Segment(0.0, 2.0, "hola mundo"), Segment(3.0, 5.0, "adios")])

    def fake_synth(text, language, reference_audio=None):
        calls["synth"].append((text, language, reference_audio))
        return wav_bytes(1.0)

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(dictation_engine, "transcribe", fake_transcribe)
    monkeypatch.setattr(translator, "translate", lambda texts, s, t: [f"[{t}] {x}" for x in texts])
    monkeypatch.setattr(cloning_engine, "synthesize", fake_synth)
    monkeypatch.setattr(jobs, "start", jobs._work)  # run synchronously
    return calls


def post(voice="original", lang="en", name="clip.mp4", data=b"fakevideo"):
    return client.post(
        "/api/dubbing/jobs",
        files={"file": (name, data, "video/mp4")},
        data={"target_language": lang, "voice": voice},
    )


def test_status():
    assert "ready" in client.get("/api/dubbing/status").json()


def test_happy_path_original_voice(mocked):
    res = post()
    assert res.status_code == 200
    job = client.get(f"/api/dubbing/jobs/{res.json()['id']}").json()
    assert job["state"] == "done" and job["percent"] == 100 and job["error"] is None
    assert [c[0] for c in mocked["synth"]] == ["[en] hola mundo", "[en] adios"]
    assert mocked["synth"][0][2].name == "reference.wav"
    jid = res.json()["id"]
    assert client.get(f"/api/dubbing/jobs/{jid}/video").content == b"video"
    srt = client.get(f"/api/dubbing/jobs/{jid}/subtitles").text
    assert "00:00:03,000 --> 00:00:05,000\n[en] adios" in srt


def test_finished_job_keeps_only_outputs_and_survives_restart(mocked, monkeypatch):
    jid = post().json()["id"]
    folder = jobs.get(jid).dir
    assert sorted(p.name for p in folder.iterdir()) == ["dubbed.mp4", "job.json", "subtitles.srt"]

    monkeypatch.setattr(jobs, "_jobs", {})  # simulate an app restart
    assert client.get(f"/api/dubbing/jobs/{jid}").json()["state"] == "done"
    assert client.get(f"/api/dubbing/jobs/{jid}/video").content == b"video"


def test_job_running_at_restart_is_marked_interrupted(mocked, monkeypatch):
    monkeypatch.setattr(jobs, "start", jobs._save)  # saved as queued, never run
    jid = post().json()["id"]
    monkeypatch.setattr(jobs, "_jobs", {})
    body = client.get(f"/api/dubbing/jobs/{jid}").json()
    assert body["state"] == "error" and body["error"] == jobs.INTERRUPTED
    assert [p.name for p in jobs.get(jid).dir.iterdir()] == ["job.json"]  # input copy removed


def test_failed_job_cleans_up(mocked, monkeypatch):
    monkeypatch.setattr(cloning_engine, "synthesize", lambda *a, **k: 1 / 0)
    jid = post().json()["id"]
    assert client.get(f"/api/dubbing/jobs/{jid}").json()["state"] == "error"
    assert [p.name for p in jobs.get(jid).dir.iterdir()] == ["job.json"]


def test_empty_upload_leaves_no_job_folder(mocked, isolated_data_dir):
    assert post(data=b"").status_code == 422
    assert not list((isolated_data_dir / "dubbing" / "jobs").glob("*"))


def test_subtitles_served_as_utf8(mocked, monkeypatch):
    monkeypatch.setattr(translator, "translate", lambda texts, s, t: ["clonación"] * len(texts))
    jid = post().json()["id"]
    res = client.get(f"/api/dubbing/jobs/{jid}/subtitles")
    assert "charset=utf-8" in res.headers["content-type"]
    assert "clonación" in res.text


def test_library_voice_used_as_reference(mocked):
    voice = voices.save_voice("Ann", wav_bytes(1.0), "upload")
    assert post(voice=voice.id).status_code == 200
    assert mocked["synth"][0][2] == voices.voice_audio_path(voice.id)


def test_progress_reported(mocked, tmp_path):
    seen = []
    (tmp_path / "v.mp4").write_bytes(b"x")
    pipeline.run(tmp_path, tmp_path / "v.mp4", "en", "original", lambda s, p: seen.append((s, p)))
    assert seen[0][0] == "Extracting audio" and seen[-1][0] == "Assembling video"
    assert [p for _, p in seen] == sorted(p for _, p in seen)


def test_output_unavailable_until_done(monkeypatch, mocked):
    monkeypatch.setattr(jobs, "start", lambda job: None)  # stay queued
    jid = post().json()["id"]
    assert client.get(f"/api/dubbing/jobs/{jid}").json()["state"] == "queued"
    assert client.get(f"/api/dubbing/jobs/{jid}/video").status_code == 409


def test_unknown_job():
    assert client.get("/api/dubbing/jobs/000000000000").status_code == 404
    assert client.get("/api/dubbing/jobs/..%2Fetc").status_code == 404
    assert client.get("/api/dubbing/jobs/000000000000/video").status_code == 404


def test_unknown_voice(mocked):
    assert post(voice="deadbeefdead").status_code == 422
    assert post(voice="../../x").status_code == 422


def test_target_language_needs_translation_and_speech(mocked):
    from voxwell.features.dubbing.translate import LANGUAGES as translatable
    from voxwell.features.voice_cloning.engine import LANGUAGES as speakable

    offered = set(client.get("/api/dubbing/status").json()["languages"])
    assert offered == translatable & speakable.keys()
    assert post(lang="vi").status_code == 422  # translatable, but no speech model support


def test_bad_language_and_file(mocked):
    assert post(lang="xx").status_code == 422
    assert post(name="notes.txt").status_code == 422
    assert post(data=b"").status_code == 422


def test_filename_is_not_a_path(mocked):
    res = post(name="../../evil.mp4")
    assert res.status_code == 200
    video = jobs.get(res.json()["id"]).video
    assert video.name == "input.mp4" and video.parent.parent.name == "jobs"


@pytest.mark.parametrize("target", ["transcribe", "translate", "synth", "ffmpeg"])
def test_failing_step_becomes_job_error(mocked, monkeypatch, target):
    def boom(*a, **k):
        raise RuntimeError("boom")

    if target == "ffmpeg":
        monkeypatch.setattr(ffmpeg, "run_ffmpeg", lambda args: (_ for _ in ()).throw(ffmpeg.DubbingError("install ffmpeg")))
    else:
        mod, name = {
            "transcribe": (dictation_engine, "transcribe"),
            "translate": (translator, "translate"),
            "synth": (cloning_engine, "synthesize"),
        }[target]
        monkeypatch.setattr(mod, name, boom)
    job = client.get(f"/api/dubbing/jobs/{post().json()['id']}").json()
    assert job["state"] == "error" and job["error"]
    assert "Traceback" not in job["error"]


def test_no_speech_is_an_error(mocked, monkeypatch):
    monkeypatch.setattr(dictation_engine, "transcribe", lambda p, language=None: Transcript("", "es", []))
    job = client.get(f"/api/dubbing/jobs/{post().json()['id']}").json()
    assert job["state"] == "error" and "No speech" in job["error"]


def test_missing_ffmpeg_message(monkeypatch):
    monkeypatch.delenv("VOXWELL_FFMPEG", raising=False)
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: None)
    with pytest.raises(ffmpeg.DubbingError, match="Install ffmpeg"):
        ffmpeg.ffmpeg_path()


def test_translate_same_language_skips_model():
    assert translator.translate(["hi"], "en", "en") == ["hi"]
    with pytest.raises(ffmpeg.DubbingError):
        translator.translate(["hi"], "en", "xx")


# --- pure time-fitting logic ---

def test_tempo_for():
    assert fitting.tempo_for(1.0, 2.0) == 1.0  # fits: not slowed
    assert fitting.tempo_for(3.0, 2.0) == pytest.approx(1.5)
    assert fitting.tempo_for(2.4, 2.0) == pytest.approx(1.2)
    assert fitting.tempo_for(10.0, 2.0) == fitting.MAX_TEMPO  # capped
    assert fitting.tempo_for(1.0, 0) == 1.0


def test_max_seconds():
    assert fitting.max_seconds(0, 2, 5) == 5  # may use the gap before the next segment
    assert fitting.max_seconds(0, 2, 1.5) == 2  # never below its own slot
    assert fitting.max_seconds(0, 2, None) == 3


def test_fit_samples_trims_with_fade():
    out = fitting.fit_samples([1000] * 100, 100, 0.5)
    assert len(out) == 50 and out[-1] < 1000
    short = [5] * 10
    assert fitting.fit_samples(short, 100, 1.0) == short


def test_srt_and_reference_window():
    assert fitting.srt_time(3661.5) == "01:01:01,500"
    assert fitting.build_srt([(0, 1.25, "a")]) == "1\n00:00:00,000 --> 00:00:01,250\na\n"
    assert fitting.reference_window([(0, 1), (5, 30)]) == (5, 12.0)
    assert fitting.reference_window([(0, 1)]) == (0, 3.0)
    assert fitting.reference_window([]) == (0.0, 8.0)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
@pytest.mark.parametrize("track_seconds", [1.0, 5.0])
def test_mux_keeps_the_whole_video(tmp_path, track_seconds):
    """A dubbed track shorter than the video must not cut the video; a longer one stops at its end."""
    video, track, out = tmp_path / "in.mp4", tmp_path / "track.wav", tmp_path / "out.mp4"
    ffmpeg.run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=64x64:r=25:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)])
    track.write_bytes(wav_bytes(track_seconds))
    pipeline.mux(video, track, out)
    probe = subprocess.run(
        [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    durations = {kind: float(seconds) for kind, seconds in (line.split(",") for line in probe)}
    assert durations["video"] == pytest.approx(3.0, abs=0.1)
    assert durations["audio"] == pytest.approx(3.0, abs=0.15)
