from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter

from voxwell.features.audiobook.router import router as audiobook
from voxwell.features.batch import watch as batch_watch
from voxwell.features.batch.router import router as batch
from voxwell.features.dictation.router import router as dictation
from voxwell.features.dubbing.router import router as dubbing
from voxwell.features.gallery.router import router as gallery
from voxwell.features.integrations.router import router as integrations
from voxwell.features.projects.router import router as projects
from voxwell.features.stories.router import router as stories
from voxwell.features.tools.router import router as tools
from voxwell.features.transcription.router import router as transcription
from voxwell.features.voice_cloning.router import router as voice_cloning
from voxwell.features.voice_design.router import router as voice_design
from voxwell.features.voices.router import router as voices


@dataclass(frozen=True)
class Feature:
    id: str
    router: APIRouter
    # Started once when the server starts (not in tests); must return quickly.
    background: Callable[[], None] | None = None


FEATURES = [
    Feature("voice_cloning", voice_cloning),
    Feature("voice_design", voice_design),
    Feature("voices", voices),
    Feature("gallery", gallery),
    Feature("stories", stories),
    Feature("audiobook", audiobook),
    Feature("dubbing", dubbing),
    Feature("batch", batch, batch_watch.start),
    Feature("dictation", dictation),
    Feature("transcription", transcription),
    Feature("tools", tools),
    Feature("integrations", integrations),
    Feature("projects", projects),
]
