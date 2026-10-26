from dataclasses import dataclass

from fastapi import APIRouter

from voxwell.features.dictation.router import router as dictation
from voxwell.features.dubbing.router import router as dubbing
from voxwell.features.projects.router import router as projects
from voxwell.features.voice_cloning.router import router as voice_cloning
from voxwell.features.voice_design.router import router as voice_design
from voxwell.features.voices.router import router as voices


@dataclass(frozen=True)
class Feature:
    id: str
    router: APIRouter


FEATURES = [
    Feature("voice_cloning", voice_cloning),
    Feature("voice_design", voice_design),
    Feature("voices", voices),
    Feature("dubbing", dubbing),
    Feature("dictation", dictation),
    Feature("projects", projects),
]
