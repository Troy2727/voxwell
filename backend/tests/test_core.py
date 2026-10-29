import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.main import app

client = TestClient(app)

FEATURE_IDS = [
    "voice_cloning", "voice_design", "voices", "voice_collections", "gallery", "stories", "audiobook", "dubbing", "batch", "dictation",
    "transcription", "tools", "integrations", "audio_effects", "pronunciation", "projects",
]


def test_https_trusts_the_os_certificate_store():
    """Model downloads/cache checks must work behind TLS-inspecting networks (see main.py)."""
    import ssl

    import truststore

    assert ssl.SSLContext is truststore.SSLContext


@pytest.mark.parametrize("feature", FEATURE_IDS)
def test_feature_packages_are_not_shadowed_by_their_routers(feature):
    """voxwell.features.<id> must stay the package (string-based patching and imports rely on it)."""
    import importlib
    import types

    import voxwell.features as features

    importlib.import_module(f"voxwell.features.{feature}")
    assert isinstance(getattr(features, feature), types.ModuleType)


def test_health_lists_all_features():
    assert client.get("/api/health").json()["features"] == FEATURE_IDS


@pytest.mark.parametrize("feature", FEATURE_IDS)
def test_every_feature_router_is_mounted(feature):
    assert client.get(f"/api/{feature}/status").status_code == 200


def test_voice_library_roundtrip():
    voice = voices.save_voice("Alice", b"RIFF....", "upload")
    assert voices.list_voices() == [voice]
    assert voices.voice_audio_path(voice.id).read_bytes() == b"RIFF...."
    assert client.get("/api/voices").json() == [{"id": voice.id, "name": "Alice", "source": "upload"}]


@pytest.mark.parametrize("bad", ["../../etc/passwd", "ABCDEF123456", "000000000000"])
def test_voice_audio_path_rejects_bad_ids(bad):
    with pytest.raises(KeyError):
        voices.voice_audio_path(bad)
