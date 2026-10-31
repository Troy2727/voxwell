import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.main import app
from voxwell.paths import download_name

client = TestClient(app, base_url="http://127.0.0.1")

FEATURE_IDS = [
    "voice_cloning", "voice_design", "voice_remix", "voices", "voice_collections", "gallery", "sound", "music", "stories", "audiobook", "dubbing", "batch", "dictation",
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


def test_child_path_stays_in_its_folder(tmp_path):
    from voxwell.paths import child_path

    assert child_path(tmp_path, "abc.wav") == tmp_path / "abc.wav"
    for name in ("../abc.wav", r"..\abc.wav", "sub/abc.wav", r"sub\abc.wav", "..", "", "C:/x.wav", "/etc/passwd"):
        with pytest.raises(ValueError):
            child_path(tmp_path, name)


@pytest.mark.parametrize("path", [
    "/api/audio_effects/audio/{}", "/api/audiobook/previews/{}", "/api/tools/audio/{}", "/api/translation/audio/{}",
    "/api/voice_remix/audio/{}", "/api/voice_design/audio/{}", "/api/voice_cloning/audio/{}", "/api/voices/{}/audio",
    "/api/sound/audio/{}", "/api/music/audio/{}",
])
@pytest.mark.parametrize("bad_id", ["..", r"..\..\x", "a" * 32 + r"\..", "%2e%2e"])
def test_audio_routes_refuse_malformed_ids_with_404(path, bad_id):
    """Each route checks the id before building a path (child_path is tested directly above), so
    a malformed id is a clean 404 rather than a 500."""
    assert client.get(path.format(bad_id)).status_code == 404


@pytest.mark.parametrize("value, network", [
    (r"\\server", True), ("//server", True), (r"\\server\share\inbox", True), ("//server/share/inbox", True),
    (r"\\?\UNC\server\share", True), (r"\\?\unc\server\share", True),
    (r"\\?\C:\videos", False), (r"\\.\C:\videos", False), (r"C:\videos", False), ("/home/me/videos", False), ("videos", False),
])
def test_network_paths_are_recognised(value, network):
    from voxwell.paths import is_network_path

    assert is_network_path(value) is network


def _held(winerror=32):
    exc = PermissionError(13, "The process cannot access the file")
    exc.winerror = winerror  # set by hand: only Windows exceptions carry it
    return exc


def test_replace_file_retries_while_windows_antivirus_holds_the_file(tmp_path, monkeypatch):
    from voxwell import paths

    calls, real = [], paths._replace

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) <= 2:
            raise _held()
        real(src, dst)

    monkeypatch.setattr(paths, "_replace", flaky)
    monkeypatch.setattr(paths, "_sleep", lambda s: None)
    (tmp_path / "a.tmp").write_text("new")
    paths.replace_file(tmp_path / "a.tmp", tmp_path / "a.json")
    assert len(calls) == 3 and (tmp_path / "a.json").read_text() == "new"


def test_replace_file_gives_up_keeps_the_error_and_removes_the_temporary_file(tmp_path, monkeypatch):
    from voxwell import paths

    original = _held()
    monkeypatch.setattr(paths, "_replace", lambda src, dst: (_ for _ in ()).throw(original))
    monkeypatch.setattr(paths, "_sleep", lambda s: None)
    monkeypatch.setattr(paths, "REPLACE_BUDGET_SECONDS", 0.0)
    (tmp_path / "a.tmp").write_text("new")
    with pytest.raises(PermissionError) as raised:
        paths.replace_file(tmp_path / "a.tmp", tmp_path / "a.json")
    assert raised.value is original and not (tmp_path / "a.tmp").exists()


def test_replace_file_does_not_retry_a_lasting_error(tmp_path, monkeypatch):
    """A read-only folder (EACCES, no winerror) fails at once on every OS; no 5-second wait."""
    from voxwell import paths

    calls = []

    def denied(src, dst):
        calls.append(dst)
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(paths, "_replace", denied)
    monkeypatch.setattr(paths, "_sleep", lambda s: pytest.fail("must not wait"))
    (tmp_path / "a.tmp").write_text("new")
    with pytest.raises(PermissionError):
        paths.replace_file(tmp_path / "a.tmp", tmp_path / "a.json")
    assert len(calls) == 1 and not (tmp_path / "a.tmp").exists()
