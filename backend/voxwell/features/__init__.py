from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter

# Routers are imported under *_router names: binding a feature's own name (e.g. `tools`) here
# would replace the voxwell.features.tools package attribute with its router object.
from voxwell.features.audio_effects.router import router as audio_effects_router
from voxwell.features.audiobook.router import router as audiobook_router
from voxwell.features.batch import watch as batch_watch
from voxwell.features.batch.router import router as batch_router
from voxwell.features.dictation.router import router as dictation_router
from voxwell.features.dubbing.router import router as dubbing_router
from voxwell.features.gallery.router import router as gallery_router
from voxwell.features.integrations import phone as integrations_phone
from voxwell.features.integrations.router import router as integrations_router
from voxwell.features.pronunciation.router import router as pronunciation_router
from voxwell.features.projects.router import router as projects_router
from voxwell.features.sound.router import router as sound_router
from voxwell.features.stories.router import router as stories_router
from voxwell.features.tools.router import router as tools_router
from voxwell.features.transcription.router import router as transcription_router
from voxwell.features.voice_cloning.router import router as voice_cloning_router
from voxwell.features.voice_collections.router import router as voice_collections_router
from voxwell.features.voice_design.router import router as voice_design_router
from voxwell.features.voices.router import router as voices_router


@dataclass(frozen=True)
class Feature:
    id: str
    router: APIRouter
    # Started once when the server starts (not in tests); must return quickly.
    background: Callable[[], None] | None = None


FEATURES = [
    Feature("voice_cloning", voice_cloning_router),
    Feature("voice_design", voice_design_router),
    Feature("voices", voices_router),
    Feature("voice_collections", voice_collections_router),
    Feature("gallery", gallery_router),
    Feature("sound", sound_router),
    Feature("stories", stories_router),
    Feature("audiobook", audiobook_router),
    Feature("dubbing", dubbing_router),
    Feature("batch", batch_router, batch_watch.start),
    Feature("dictation", dictation_router),
    Feature("transcription", transcription_router),
    Feature("tools", tools_router),
    Feature("integrations", integrations_router, integrations_phone.sync_gateway),
    Feature("audio_effects", audio_effects_router),
    Feature("pronunciation", pronunciation_router),
    Feature("projects", projects_router),
]
