"""Voice collections: folders that organize the saved voices."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from voxwell import voice_collections, voices

router = APIRouter(tags=["voice_collections"])


class NameRequest(BaseModel):
    name: str


def _collection(collection_id: str) -> voice_collections.Collection:
    try:
        return voice_collections.get_collection(collection_id)
    except KeyError:
        raise HTTPException(404, "Unknown collection.")


def _voice(voice_id: str) -> None:
    try:
        voices.get_voice(voice_id)
    except KeyError:
        raise HTTPException(404, "Unknown voice.")


@router.get("/status")
def status():
    return {"ready": True}


@router.get("")
def list_collections():
    return [asdict(c) for c in voice_collections.list_collections()]


@router.post("", status_code=201)
def create(req: NameRequest):
    try:
        return asdict(voice_collections.create_collection(req.name))
    except voice_collections.InvalidName as exc:
        raise HTTPException(409 if "already" in str(exc) else 422, str(exc))


@router.patch("/{collection_id}")
def rename(collection_id: str, req: NameRequest):
    try:
        return asdict(voice_collections.rename_collection(collection_id, req.name))
    except KeyError:
        raise HTTPException(404, "Unknown collection.")
    except voice_collections.InvalidName as exc:
        raise HTTPException(409 if "already" in str(exc) else 422, str(exc))


@router.delete("/{collection_id}")
def delete(collection_id: str):
    try:
        voice_collections.delete_collection(collection_id)
    except KeyError:
        raise HTTPException(404, "Unknown collection.")
    return {"deleted": collection_id}


@router.get("/{collection_id}/voices")
def collection_voices(collection_id: str):
    ids = _collection(collection_id).voice_ids
    found = []
    for voice_id in ids:
        try:
            found.append(asdict(voices.get_voice(voice_id)))
        except KeyError:
            continue
    return found


@router.put("/{collection_id}/voices/{voice_id}")
def add_voice(collection_id: str, voice_id: str):
    _collection(collection_id)
    _voice(voice_id)
    return asdict(voice_collections.add_voice(collection_id, voice_id))


@router.delete("/{collection_id}/voices/{voice_id}")
def remove_voice(collection_id: str, voice_id: str):
    _collection(collection_id)
    return asdict(voice_collections.remove_voice(collection_id, voice_id))
