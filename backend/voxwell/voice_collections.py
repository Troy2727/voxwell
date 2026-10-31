"""Folders for saved voices: named, ordered lists of voice ids.

Stored as one JSON file, kept out of the voices folder so it is never mistaken for a voice.
Collections only reference voices; deleting a collection never deletes a voice, and deleting a
voice removes it from every collection (see voices.delete_voice).
"""

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field

from voxwell.paths import data_dir, replace_file

_LOCK = threading.RLock()


@dataclass
class Collection:
    id: str
    name: str
    voice_ids: list[str] = field(default_factory=list)


class InvalidName(ValueError):
    """The name is empty or already used by another collection."""


def _path():
    return data_dir("voice_collections") / "collections.json"


def _load() -> list[Collection]:
    try:
        return [Collection(**c) for c in json.loads(_path().read_text(encoding="utf-8"))]
    except FileNotFoundError:
        return []


def _save(collections: list[Collection]) -> None:
    path = _path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(c) for c in collections]), encoding="utf-8")
    replace_file(tmp, path)


def _clean_name(name: str, others: list[Collection]) -> str:
    name = name.strip()
    if not name:
        raise InvalidName("Collection name is required.")
    if any(c.name.casefold() == name.casefold() for c in others):
        raise InvalidName(f"A collection named '{name}' already exists.")
    return name


def _find(collections: list[Collection], collection_id: str) -> Collection:
    for c in collections:
        if c.id == collection_id:
            return c
    raise KeyError(collection_id)


def list_collections() -> list[Collection]:
    with _LOCK:
        return _load()


def get_collection(collection_id: str) -> Collection:
    """KeyError if unknown."""
    with _LOCK:
        return _find(_load(), collection_id)


def create_collection(name: str) -> Collection:
    with _LOCK:
        collections = _load()
        collection = Collection(id=uuid.uuid4().hex[:12], name=_clean_name(name, collections))
        _save([*collections, collection])
        return collection


def rename_collection(collection_id: str, name: str) -> Collection:
    with _LOCK:
        collections = _load()
        collection = _find(collections, collection_id)
        collection.name = _clean_name(name, [c for c in collections if c.id != collection_id])
        _save(collections)
        return collection


def delete_collection(collection_id: str) -> None:
    with _LOCK:
        collections = _load()
        collection = _find(collections, collection_id)
        _save([c for c in collections if c is not collection])


def add_voice(collection_id: str, voice_id: str) -> Collection:
    """Append a voice (a no-op when it is already in the collection)."""
    with _LOCK:
        collections = _load()
        collection = _find(collections, collection_id)
        if voice_id not in collection.voice_ids:
            collection.voice_ids.append(voice_id)
            _save(collections)
        return collection


def remove_voice(collection_id: str, voice_id: str) -> Collection:
    with _LOCK:
        collections = _load()
        collection = _find(collections, collection_id)
        if voice_id in collection.voice_ids:
            collection.voice_ids.remove(voice_id)
            _save(collections)
        return collection


def remove_voice_everywhere(voice_id: str) -> None:
    with _LOCK:
        collections = _load()
        changed = False
        for c in collections:
            if voice_id in c.voice_ids:
                c.voice_ids.remove(voice_id)
                changed = True
        if changed:
            _save(collections)
