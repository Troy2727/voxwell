import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.main import app
from voxwell.paths import download_name

client = TestClient(app, base_url="http://127.0.0.1")

FEATURE_IDS = [
    "voice_cloning", "voice_design", "voices", "voice_collections", "gallery", "sound", "stories", "audiobook", "dubbing", "batch", "dictation",
    "transcription", "translation", "tools", "agents", "integrations", "audio_effects", "pronunciation", "projects",
]


def test_https_trusts_the_os_certificate_store():
    """Model downloads/cache checks must work behind TLS-inspecting networks (see main.py)."""
    import ssl

    import truststore

    assert ssl.SSLContext is truststore.SSLContext


def _preflight(origin: str):
    return client.options("/api/voices", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Private-Network": "true",
    })


def test_the_website_may_use_the_local_backend():
    """voxwell.vercel.app is the hosted UI; it talks to the backend on the visitor's own computer.
    Chrome asks a public page's permission to reach 127.0.0.1 with a private-network preflight."""
    r = _preflight("https://voxwell.vercel.app")
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://voxwell.vercel.app"
    assert r.headers["access-control-allow-private-network"] == "true"


def test_the_desktop_app_may_use_the_backend():
    """The packaged desktop UI loads from app://voxwell (app/electron/main.cjs)."""
    r = _preflight("app://voxwell")
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "app://voxwell"


# "null" is the origin of file:// pages, but also of sandboxed iframes and data: URLs on any website.
@pytest.mark.parametrize("origin", ["https://evil.example", "https://voxwell.vercel.app.evil.example", "http://voxwell.vercel.app", "null"])
def test_other_web_pages_still_may_not(origin):
    r = _preflight(origin)
    assert r.status_code == 400 and "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost:8765"])
def test_requests_to_this_computer_are_served(host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


def test_requests_for_other_host_names_are_refused():
    """A website whose name was re-pointed at 127.0.0.1 (DNS rebinding) must not reach the API."""
    assert client.get("/api/voices", headers={"Host": "attacker.example:8765"}).status_code == 400


@pytest.mark.parametrize("title", ["..\\..\\escape", "../../escape", "a\\b/c"])
def test_download_names_have_no_path_separators(title):
    name = download_name(title, ".wav", "Chapter")
    assert "/" not in name and "\\" not in name


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
