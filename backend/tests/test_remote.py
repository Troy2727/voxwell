import pytest
from fastapi.testclient import TestClient

from voxwell import cli, remote
from voxwell.features.dictation import engine
from voxwell.main import app

HOST = "my-pc.tail1234.ts.net"
OWNER = "owner@example.com"
SELF = f"https://{HOST}"
OK = {"Tailscale-User-Login": OWNER, "Origin": SELF}


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(remote.HOST_ENV, HOST)
    monkeypatch.setenv(remote.OWNER_ENV, OWNER)


@pytest.fixture
def phone(on):
    return TestClient(app, base_url=SELF)


@pytest.fixture
def fake_whisper(monkeypatch):
    def fake(path, language=None, speech_only=True):
        return engine.Transcript("hola", language or "es", [engine.Segment(0.0, 1.0, "hola")])

    monkeypatch.setattr(engine, "transcribe", fake)


def dictate(client, headers=OK):
    return client.post("/api/dictation/transcribe", headers=headers, files={"file": ("recording", b"audio")})


def test_the_owner_gets_the_page_and_can_dictate(phone, fake_whisper):
    page = phone.get("/", headers={"Tailscale-User-Login": OWNER})
    assert page.status_code == 200
    assert "Voxwell Dictation" in page.text
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert page.headers["cache-control"] == "no-store"
    r = dictate(phone)
    assert r.status_code == 200 and r.json()["text"] == "hola"


def test_the_account_name_isnt_case_sensitive(phone, fake_whisper):
    assert dictate(phone, {**OK, "Tailscale-User-Login": "Owner@Example.COM"}).status_code == 200


@pytest.mark.parametrize("login", ["someone-else@example.com", "", None])
def test_any_other_account_is_refused_everywhere(phone, fake_whisper, login):
    headers = {"Origin": SELF} | ({"Tailscale-User-Login": login} if login is not None else {})
    assert dictate(phone, headers).status_code == 403
    assert phone.get("/", headers=headers).status_code == 403
    assert phone.get("/api/health", headers=headers).status_code == 403


@pytest.mark.parametrize("origin", ["https://evil.example", "null", f"http://{HOST}", f"https://{HOST}.evil.example", None])
def test_other_websites_on_the_phone_cant_dictate(phone, fake_whisper, origin):
    headers = {"Tailscale-User-Login": OWNER} | ({"Origin": origin} if origin else {})
    assert dictate(phone, headers).status_code == 403


def test_another_website_cant_read_the_page_either(phone):
    assert phone.get("/", headers={**OK, "Origin": "https://evil.example"}).status_code == 403


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/voices"),
        ("POST", "/api/voice_cloning/synthesize"),
        ("GET", "/api/projects/items"),
        ("POST", "/v1/audio/speech"),
        ("POST", "/v1/audio/transcriptions"),
        ("GET", "/docs"),
        ("GET", "/openapi.json"),
        ("DELETE", "/api/dictation/transcribe"),
        ("GET", "/api/dictation/transcribe"),
        ("POST", "/"),
        ("GET", "/api/dictation/status/../../voices"),
    ],
)
def test_only_dictation_can_be_reached_even_by_the_owner(phone, method, path):
    assert phone.request(method, path, headers=OK).status_code == 404


def test_the_live_websocket_is_closed_for_the_phone(phone):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), phone.websocket_connect(f"wss://{HOST}/api/dictation/live", headers=OK):
        pass


def test_a_look_alike_host_gets_no_special_treatment(on):
    """Another *.ts.net name re-pointed at this computer: still refused, as any unknown name is."""
    for host in ("https://evil.ts.net", f"https://{HOST}.evil.example", "https://tail1234.ts.net"):
        client = TestClient(app, base_url=host)
        assert client.get("/api/health", headers=OK).status_code == 403
        assert client.get("/api/health").status_code == 400


@pytest.mark.parametrize(
    "proxied",
    [
        {"X-Forwarded-Host": HOST},
        {"Tailscale-User-Login": OWNER},
        {"Tailscale-Funnel-Request": "?1"},
    ],
)
@pytest.mark.parametrize("remote_on", [True, False])
def test_a_proxied_request_cant_pass_as_local_by_faking_the_address(monkeypatch, proxied, remote_on):
    """`tailscale serve` passes on the Host it was given, so a client on the network could send "Host: 127.0.0.1"."""
    if remote_on:
        monkeypatch.setenv(remote.HOST_ENV, HOST)
        monkeypatch.setenv(remote.OWNER_ENV, OWNER)
    else:
        monkeypatch.delenv(remote.HOST_ENV, raising=False)
        monkeypatch.delenv(remote.OWNER_ENV, raising=False)
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get("/api/voices", headers=proxied).status_code == 403
    assert client.get("/api/voices").status_code == 200


def test_a_proxied_websocket_cant_pass_as_local(monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.delenv(remote.HOST_ENV, raising=False)
    client = TestClient(app, base_url="http://127.0.0.1")
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/dictation/live", headers={"X-Forwarded-Host": HOST}):
        pass


def test_the_local_app_is_untouched_when_remote_is_on(on, fake_whisper):
    local = TestClient(app, base_url="http://127.0.0.1")
    assert local.get("/api/voices").status_code == 200
    assert local.get("/").status_code == 404
    assert dictate(local, {}).status_code == 200


def test_with_remote_off_a_remote_name_is_refused_like_any_other(monkeypatch):
    monkeypatch.delenv(remote.HOST_ENV, raising=False)
    monkeypatch.delenv(remote.OWNER_ENV, raising=False)
    client = TestClient(app, base_url=SELF)
    assert client.get("/", headers=OK).status_code == 403
    assert client.get("/").status_code == 400


def test_a_host_set_without_an_owner_lets_nobody_in(monkeypatch):
    monkeypatch.setenv(remote.HOST_ENV, HOST)
    monkeypatch.delenv(remote.OWNER_ENV, raising=False)
    assert TestClient(app, base_url=SELF).get("/", headers=OK).status_code == 403


STATUS = {"BackendState": "Running", "Self": {"DNSName": "My-PC.tail1234.ts.net.", "UserID": 7}, "User": {"7": {"LoginName": OWNER}}}


def test_the_name_and_account_come_from_tailscale():
    assert remote.identity_from_status(STATUS) == ("my-pc.tail1234.ts.net", OWNER)


@pytest.mark.parametrize(
    "broken",
    [
        {**STATUS, "BackendState": "NeedsLogin"},
        {**STATUS, "Self": {"UserID": 7}},
        {**STATUS, "User": {}},
        {},
    ],
)
def test_tailscale_not_ready_says_what_to_do(broken):
    with pytest.raises(remote.RemoteSetupError, match="sign in"):
        remote.identity_from_status(broken)


def test_serve_remote_turns_it_on_and_prints_the_steps(monkeypatch, capsys):
    import voxwell.main

    monkeypatch.delenv(remote.HOST_ENV, raising=False)
    monkeypatch.delenv(remote.OWNER_ENV, raising=False)
    monkeypatch.setattr(remote, "detect_identity", lambda: (HOST, OWNER))
    started = []
    monkeypatch.setattr(voxwell.main, "run", lambda: started.append(True))
    assert cli.main(["serve", "--remote"]) == 0
    assert started == [True]
    assert remote.HOST_ENV in __import__("os").environ
    out = capsys.readouterr().out
    assert f"https://{HOST}" in out and "tailscale serve --bg" in out and OWNER in out
    monkeypatch.delenv(remote.HOST_ENV)
    monkeypatch.delenv(remote.OWNER_ENV)


def test_serve_remote_without_tailscale_fails_with_a_reason_and_doesnt_start(monkeypatch, capsys):
    import voxwell.main

    def missing():
        raise remote.RemoteSetupError("Tailscale isn't installed.")

    monkeypatch.setattr(remote, "detect_identity", missing)
    started = []
    monkeypatch.setattr(voxwell.main, "run", lambda: started.append(True))
    assert cli.main(["serve", "--remote"]) == 1
    assert started == []
    assert "Tailscale isn't installed." in capsys.readouterr().err


def test_plain_serve_stays_local(monkeypatch):
    import voxwell.main

    monkeypatch.delenv(remote.HOST_ENV, raising=False)
    monkeypatch.setattr(voxwell.main, "run", lambda: None)
    assert cli.main(["serve"]) == 0
    assert cli.main([]) == 0
    assert remote.HOST_ENV not in __import__("os").environ


def test_the_page_ships_with_the_package():
    assert remote.PAGE.exists()
    assert "<script src" not in remote.PAGE.read_text(encoding="utf-8"), "everything is inline, so the strict policy holds"


WEBSITE = "https://voxwell.vercel.app"


def test_the_owner_can_dictate_from_the_website_and_the_browser_may_read_the_answer(phone, fake_whisper):
    r = dictate(phone, {"Tailscale-User-Login": OWNER, "Origin": WEBSITE})
    assert r.status_code == 200 and r.json()["text"] == "hola"
    assert r.headers["access-control-allow-origin"] == WEBSITE


def test_the_browser_may_ask_first_before_the_website_dictates(phone):
    r = phone.options(
        "/api/dictation/transcribe",
        headers={"Tailscale-User-Login": OWNER, "Origin": WEBSITE, "Access-Control-Request-Method": "POST", "Access-Control-Request-Private-Network": "true"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == WEBSITE
    assert r.headers["access-control-allow-private-network"] == "true"


def test_the_website_still_needs_the_owners_account(phone, fake_whisper):
    assert dictate(phone, {"Tailscale-User-Login": "someone@else.com", "Origin": WEBSITE}).status_code == 403
    assert dictate(phone, {"Origin": WEBSITE}).status_code == 403


FROM_WEBSITE = {"Tailscale-User-Login": OWNER, "Origin": WEBSITE}


@pytest.mark.parametrize("path", ["/api/voices", "/api/gallery/presets", "/api/projects/items"])
def test_the_website_on_a_phone_reaches_the_whole_app(phone, path):
    r = phone.get(path, headers=FROM_WEBSITE)
    assert r.status_code == 200, f"{path} gave {r.status_code}"
    assert r.headers["access-control-allow-origin"] == WEBSITE


def test_the_browser_may_ask_first_for_any_feature(phone):
    r = phone.options("/api/voices", headers={**FROM_WEBSITE, "Access-Control-Request-Method": "DELETE", "Access-Control-Request-Private-Network": "true"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == WEBSITE


def test_the_website_gets_the_app_not_the_phone_page(phone):
    assert "voxwell dictation" not in phone.get("/", headers=FROM_WEBSITE).text.lower()


def test_the_website_on_a_phone_can_use_the_live_features(phone):
    with phone.websocket_connect(f"wss://{HOST}/api/agents/agents/0123456789ab/live", headers=FROM_WEBSITE) as ws:
        ws.send_json({"type": "start", "config": {}})
        assert ws.receive_json() == {"type": "error", "message": "Unknown agent."}


@pytest.mark.parametrize("headers", [{"Origin": WEBSITE}, {"Tailscale-User-Login": "someone@else.com", "Origin": WEBSITE}, {"Tailscale-User-Login": OWNER, "Origin": "https://evil.example"}])
def test_the_live_features_still_need_the_owner_and_the_website(phone, headers):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), phone.websocket_connect(f"wss://{HOST}/api/agents/agents/0123456789ab/live", headers=headers):
        pass


def test_another_account_gets_nothing_from_the_website_either(phone):
    assert phone.get("/api/voices", headers={"Tailscale-User-Login": "someone@else.com", "Origin": WEBSITE}).status_code == 403


@pytest.mark.parametrize("origin", ["https://voxwell.vercel.app.evil.example", "https://evil-voxwell.vercel.app", "http://voxwell.vercel.app", "https://voxwell.vercel.app:8443"])
def test_look_alikes_of_the_website_are_refused(phone, fake_whisper, origin):
    assert dictate(phone, {"Tailscale-User-Login": OWNER, "Origin": origin}).status_code == 403
