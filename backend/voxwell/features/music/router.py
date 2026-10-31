"""Music: songs and instrumentals from a description and lyrics, generated on this computer by
ACE-Step 1.5. Tracks can have a section regenerated, and can be split into vocals and instrumental
with the voice isolation model from Tools."""

import asyncio
import random
import uuid
from dataclasses import asdict

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from voxwell.features.music import engine, history, jobs, lyrics, runtime
from voxwell.features.tools import isolation
from voxwell.features.tools.router import _read_audio
from voxwell.paths import attachment, download_name

router = APIRouter(tags=["music"])
_stems_lock = asyncio.Lock()

MAX_PROMPT = 512  # ACE-Step's caption limit
MAX_LYRICS = 4096
MIN_SECONDS, MAX_SECONDS = 10, 300
MIN_EDIT_SECONDS = 3
MAX_REFERENCE_SECONDS = 120
DEFAULT_STEPS = 8  # the turbo model's own default
NOTES = ("C", "C#", "Db", "D", "D#", "Eb", "E", "F", "F#", "Gb", "G", "G#", "Ab", "A", "A#", "Bb", "B")
KEYS = [f"{note} {mode}" for note in NOTES for mode in ("major", "minor")]


def _item(track: history.Track) -> dict:
    urls = {}
    if track.status == "done":
        urls["url"] = f"/api/music/audio/{track.id}"
        if track.stems:
            urls["vocals_url"] = f"/api/music/audio/{track.id}?part=vocals"
            urls["instrumental_url"] = f"/api/music/audio/{track.id}?part=instrumental"
    return {**asdict(track), **urls}


def _track(track_id: str) -> history.Track:
    try:
        track = history.get(track_id)
    except KeyError:
        raise HTTPException(404, "Track not found.")
    return _settle(track)


def _settle(track: history.Track) -> history.Track:
    """A track left queued or generating by an earlier run of Voxwell will never finish."""
    if track.status in ("queued", "generating") and not jobs.is_active(track.id):
        track = history.update(track.id, status="failed", stage="Failed", error="Voxwell closed before this track finished.")
    return track


@router.get("/status")
def status():
    from voxwell.features.voice_cloning.engine import _pick_device

    return {
        "installed": runtime.is_installed(),
        "install": runtime.install_state(),
        "engine": runtime.engine_state(),
        "device": _pick_device(),
        "languages": engine.LANGUAGES,
        "keys": KEYS,
        "limits": {"min_seconds": MIN_SECONDS, "max_seconds": MAX_SECONDS, "max_prompt": MAX_PROMPT, "max_lyrics": MAX_LYRICS},
    }


@router.post("/install")
def install():
    if runtime.is_installed():
        return {"started": False, "installed": True}
    if not runtime.start_install():
        raise HTTPException(409, "The music engine is already being installed.")
    return {"started": True, "installed": False}


class LyricsRequest(BaseModel):
    description: str = Field(min_length=1, max_length=MAX_PROMPT)
    language: str = "en"


@router.post("/lyrics")
async def write_lyrics(req: LyricsRequest):
    if req.language not in engine.LANGUAGES:
        raise HTTPException(422, f"Unsupported language '{req.language}'.")
    try:
        text = await asyncio.to_thread(lyrics.write, req.description.strip(), engine.LANGUAGES[req.language])
    except lyrics.LyricsError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Writing lyrics failed: {type(exc).__name__}")
    return {"lyrics": text[:MAX_LYRICS]}


@router.post("/generate")
async def generate(
    prompt: str = Form(...),
    lyrics_text: str = Form("", alias="lyrics"),
    instrumental: bool = Form(False),
    language: str = Form("en"),
    duration: float = Form(30),
    bpm: int | None = Form(None),
    key: str = Form(""),
    seed: int | None = Form(None),
    steps: int = Form(DEFAULT_STEPS),
    title: str = Form(""),
    file: UploadFile | None = File(None),  # optional style reference
):
    _require_installed()
    prompt, lyrics_text, key = prompt.strip(), lyrics_text.strip(), key.strip()
    if not prompt:
        raise HTTPException(422, "Describe the music you want.")
    if len(prompt) > MAX_PROMPT:
        raise HTTPException(422, f"The description is too long ({MAX_PROMPT} characters max).")
    if len(lyrics_text) > MAX_LYRICS:
        raise HTTPException(422, f"The lyrics are too long ({MAX_LYRICS} characters max).")
    if not instrumental and not lyrics_text:
        raise HTTPException(422, "Add lyrics (or let AI write them), or choose instrumental.")
    if language not in engine.LANGUAGES:
        raise HTTPException(422, f"Unsupported language '{language}'.")
    if not MIN_SECONDS <= duration <= MAX_SECONDS:
        raise HTTPException(422, f"Choose a length from {MIN_SECONDS} to {MAX_SECONDS} seconds.")
    if bpm is not None and not 30 <= bpm <= 300:
        raise HTTPException(422, "Tempo must be 30 to 300 BPM.")
    if key and key not in KEYS:
        raise HTTPException(422, "Choose a key from the list.")
    if seed is not None and not 0 <= seed < 2**32:
        raise HTTPException(422, "The seed must be a whole number from 0 to 4294967295.")
    if not 4 <= steps <= 20:
        raise HTTPException(422, "Quality steps must be 4 to 20.")

    track = history.Track(
        id=uuid.uuid4().hex,
        title=" ".join((title or prompt).split())[:80],
        prompt=prompt,
        lyrics="" if instrumental else lyrics_text,
        instrumental=instrumental,
        language=language,
        duration=duration,
        bpm=bpm,
        key=key,
        seed=seed if seed is not None else random.randrange(2**32),
        steps=steps,
        created=0,
    )
    files, cleanup = {}, []
    if file is not None and file.filename:
        wav, seconds = await _read_audio(file)
        if seconds > MAX_REFERENCE_SECONDS:
            raise HTTPException(422, f"Use a reference of up to {MAX_REFERENCE_SECONDS // 60} minutes.")
        track.has_reference = True
        path = history.scratch_path(track.id, "reference")
        path.write_bytes(wav)
        files["reference_audio"], cleanup = path, [path]
    jobs.claim(track.id)  # before the record exists, so a concurrent list never settles it as orphaned
    history.create(track)
    fields = {
        "task_type": "text2music",
        "prompt": prompt,
        "lyrics": "[Instrumental]" if instrumental else lyrics_text,
        "vocal_language": language,
        "audio_duration": duration,
        "bpm": bpm,
        "key_scale": key or None,
        "inference_steps": steps,
        "use_random_seed": False,
        "seed": track.seed,
    }
    jobs.submit(track.id, fields, files, cleanup)
    return _item(track)


class EditRequest(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    prompt: str = Field(default="", max_length=MAX_PROMPT)
    lyrics: str = Field(default="", max_length=MAX_LYRICS)


@router.post("/tracks/{track_id}/edit")
def edit_section(track_id: str, req: EditRequest):
    """Regenerate the section from `start` to `end` seconds as a new track; the rest stays."""
    import soundfile as sf

    _require_installed()
    parent = _track(track_id)
    if parent.status != "done":
        raise HTTPException(409, "Wait for the track to finish first.")
    length = sf.info(str(history.audio_path(parent.id))).duration
    if req.end > length + 0.05 or req.end - req.start < MIN_EDIT_SECONDS:
        raise HTTPException(422, f"Pick a section of at least {MIN_EDIT_SECONDS} seconds inside the track ({length:.0f} s).")
    prompt = req.prompt.strip() or parent.prompt
    new_lyrics = req.lyrics.strip() or parent.lyrics
    new_id = uuid.uuid4().hex
    jobs.claim(new_id)
    track = history.create(history.Track(
        id=new_id,
        title=f"{parent.title[:71]} (edited)",
        prompt=prompt,
        lyrics=new_lyrics,
        instrumental=parent.instrumental,
        language=parent.language,
        duration=round(length, 2),
        bpm=parent.bpm,
        key=parent.key,
        seed=random.randrange(2**32),
        steps=parent.steps,
        created=0,
        parent_id=parent.id,
        edit_start=req.start,
        edit_end=min(req.end, length),
    ))
    fields = {
        "task_type": "repaint",
        "prompt": prompt,
        "lyrics": "[Instrumental]" if parent.instrumental else new_lyrics,
        "vocal_language": parent.language,
        "repainting_start": track.edit_start,
        "repainting_end": track.edit_end,
        "chunk_mask_mode": "explicit",
        "inference_steps": parent.steps,
        "use_random_seed": False,
        "seed": track.seed,
    }
    jobs.submit(track.id, fields, {"src_audio": history.audio_path(parent.id)}, [])
    return _item(track)


@router.post("/tracks/{track_id}/stems")
async def split_stems(track_id: str):
    """Split a finished track into vocals and instrumental (the Tools voice isolation model)."""
    track = _track(track_id)
    if track.status != "done":
        raise HTTPException(409, "Wait for the track to finish first.")
    async with _stems_lock:  # one split at a time: two would write (and clean up) the same files
        track = _track(track_id)
        if not track.stems:
            vocals = history.part_path(track.id, "vocals")
            instrumental = history.part_path(track.id, "instrumental")
            try:
                await asyncio.to_thread(isolation.isolate, history.audio_path(track.id), vocals, instrumental)
            except Exception as exc:
                vocals.unlink(missing_ok=True)
                instrumental.unlink(missing_ok=True)
                if isinstance(exc, isolation.IsolationError):
                    raise HTTPException(422, str(exc))
                raise HTTPException(500, f"Splitting the track failed: {type(exc).__name__}")
            try:
                track = history.update(track.id, stems=True)
            except KeyError:
                raise HTTPException(404, "Track not found.")
    return _item(track)


@router.get("/tracks")
def list_tracks():
    return [_item(_settle(t)) for t in history.list_tracks()]


@router.get("/tracks/{track_id}")
def get_track(track_id: str):
    return _item(_track(track_id))


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)


@router.patch("/tracks/{track_id}")
def rename(track_id: str, req: RenameRequest):
    _track(track_id)
    title = " ".join(req.title.split())
    if not title:
        raise HTTPException(422, "Give the track a title.")
    try:
        return _item(history.update(track_id, title=title))
    except KeyError:
        raise HTTPException(404, "Track not found.")


@router.delete("/tracks/{track_id}")
def delete(track_id: str):
    try:
        history.delete(track_id)
    except KeyError:
        raise HTTPException(404, "Track not found.")
    return {"deleted": track_id}


@router.get("/audio/{track_id}")
def audio(track_id: str, part: str = "mix"):
    try:
        path = history.audio_path(track_id, part)
        title = history.get(track_id).title
    except KeyError:
        raise HTTPException(404, "Audio not found.")
    suffix = ".wav" if part == "mix" else f" ({part}).wav"
    name = download_name(title, suffix, f"voxwell-music-{track_id[:8]}")
    return FileResponse(path, media_type="audio/wav", headers=attachment(name))


def _require_installed() -> None:
    if not runtime.is_installed():
        raise HTTPException(409, "Install the music engine first.")
