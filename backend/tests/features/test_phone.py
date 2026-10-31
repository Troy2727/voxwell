import io
import socket
import time
import urllib.error
import urllib.request
import wave

import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.features.integrations import phone
from voxwell.features.voice_cloning import engine as cloning_engine
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")
PUBLIC = "https://calls.example.trycloudflare.com"
TOKEN = "twilio-auth-token"
CALL = {"CallSid": "CA123", "From": "+15551234567", "To": "+15005550006", "CallStatus": "ringing"}


def wav_bytes(seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x01\x00" * int(seconds * 24000))
    return buf.getvalue()


@pytest.fixture
def synth(monkeypatch):
    calls = []
    monkeypatch.setattr(cloning_engine, "synthesize", lambda t, l, r=None, **k: calls.append((t, l, r and r.stem)) or wav_bytes())
    return calls


@pytest.fixture(autouse=True)
def no_real_gateway(monkeypatch):
    """Most tests check settings, not the server: keep the gateway from binding a port."""
    monkeypatch.setattr(phone, "start_gateway", lambda: None)


def settings(**overrides):
    body = {"enabled": False, "public_url": PUBLIC, "auth_token": TOKEN, "greeting_text": "Hello! You reached Voxwell.", "voice_id": "", "language": "en"}
    return client.put("/api/integrations/phone", json={**body, **overrides})


def signed(params, token=TOKEN, url=f"{PUBLIC}/twilio/voice"):
    return {"X-Twilio-Signature": phone.signature(token, url, params)}


# --- the signature -------------------------------------------------------------------------


def test_signature_matches_twilios_documented_example():
    # From Twilio's security docs; also checked against twilio-python's RequestValidator.
    params = {"CallSid": "CA1234567890ABCDE", "Caller": "+12349013030", "Digits": "1234", "From": "+12349013030", "To": "+18005551212"}
    assert phone.signature("12345", "https://mycompany.com/myapp.php?foo=1&bar=2", params) == "0/KCTR6DLpKmkAf8muzZqo1nDgQ="


@pytest.mark.parametrize("token,given", [("", "x"), (TOKEN, ""), (TOKEN, "wrong")])
def test_invalid_signatures(token, given):
    assert not phone.is_valid(token, f"{PUBLIC}/twilio/voice", CALL, given)


# --- settings ------------------------------------------------------------------------------


def test_off_by_default_and_token_never_returned():
    body = client.get("/api/integrations/phone").json()
    assert body["enabled"] is False and body["auth_token_set"] is False and body["gateway_running"] is False
    saved = settings().json()
    assert saved["auth_token_set"] is True and TOKEN not in str(saved)
    assert saved["webhook_url"] == f"{PUBLIC}/twilio/voice" and saved["gateway"] == "http://127.0.0.1:8766"


def test_token_is_kept_unless_replaced():
    settings()
    assert settings(auth_token=None).json()["auth_token_set"] is True
    assert settings(auth_token="").json()["auth_token_set"] is False


@pytest.mark.parametrize("overrides,message", [
    ({"public_url": "http://insecure.example.com"}, "https://"),
    ({"public_url": "https://a b.com"}, "https://"),
    ({"enabled": True, "auth_token": ""}, "Auth Token"),
    ({"enabled": True, "public_url": ""}, "public address"),
    ({"language": "xx"}, "language"),
    ({"voice_id": "Nobody"}, "voice"),
    ({"greeting_text": "x" * 501}, "too long"),
])
def test_settings_validation(overrides, message):
    r = settings(**overrides)
    assert r.status_code == 422 and message in r.json()["detail"]
    assert client.get("/api/integrations/phone").json()["enabled"] is False


def test_greeting_is_rendered_in_the_chosen_voice(synth):
    voice = voices.save_voice("Receptionist", wav_bytes(), "upload")
    settings(voice_id=voice.id, language="es")
    body = client.post("/api/integrations/phone/greeting").json()
    assert body["greeting_ready"] and synth == [("Hello! You reached Voxwell.", "es", voice.id)]
    assert client.get("/api/integrations/phone/greeting.wav").content[:4] == b"RIFF"


def test_changing_the_greeting_needs_a_new_recording(synth):
    settings()
    client.post("/api/integrations/phone/greeting")
    assert settings(greeting_text="New hours: 9 to 5.").json()["greeting_ready"] is False


def test_greeting_needs_text():
    settings(greeting_text="")
    assert client.post("/api/integrations/phone/greeting").status_code == 422


# --- the public gateway --------------------------------------------------------------------


@pytest.fixture
def gateway(synth):
    settings(enabled=True)
    client.post("/api/integrations/phone/greeting")
    return TestClient(phone.build_gateway())


def test_signed_call_plays_the_greeting_and_is_logged(gateway):
    r = gateway.post("/twilio/voice", data=CALL, headers=signed(CALL))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/xml")
    token = phone.load()["greeting_token"]
    assert f"<Play>{PUBLIC}/twilio/greeting/{token}.wav</Play><Hangup/>" in r.text
    assert gateway.get(f"/twilio/greeting/{token}.wav").content[:4] == b"RIFF"
    calls = client.get("/api/integrations/phone").json()["calls"]
    assert len(calls) == 1 and calls[0]["from"] == "…67"  # only the last two digits are kept


@pytest.mark.parametrize("headers", [{}, {"X-Twilio-Signature": "forged"}])
def test_unsigned_or_forged_calls_are_rejected(gateway, headers):
    assert gateway.post("/twilio/voice", data=CALL, headers=headers).status_code == 403
    assert client.get("/api/integrations/phone").json()["calls"] == []


def test_signature_must_cover_the_exact_parameters(gateway):
    tampered = {**CALL, "From": "+19999999999"}
    assert gateway.post("/twilio/voice", data=tampered, headers=signed(CALL)).status_code == 403


def test_greeting_link_needs_the_current_token(gateway):
    old = phone.load()["greeting_token"]
    client.post("/api/integrations/phone/greeting")  # re-render: new link
    assert gateway.get(f"/twilio/greeting/{old}.wav").status_code == 404
    assert gateway.get("/twilio/greeting/" + "0" * 32 + ".wav").status_code == 404


def test_disabled_phone_answers_nothing(gateway):
    token = phone.load()["greeting_token"]
    settings(enabled=False, auth_token=None)
    assert gateway.post("/twilio/voice", data=CALL, headers=signed(CALL)).status_code == 403
    assert gateway.get(f"/twilio/greeting/{token}.wav").status_code == 404


def test_without_a_greeting_the_call_hangs_up(synth):
    settings(enabled=True)
    r = TestClient(phone.build_gateway()).post("/twilio/voice", data=CALL, headers=signed(CALL))
    assert r.text.endswith("<Response><Hangup/></Response>")


def test_gateway_exposes_nothing_else(gateway):
    for path in ("/api/voices", "/api/health", "/v1/models", "/docs", "/openapi.json"):
        assert gateway.get(path).status_code == 404


# --- the real server -----------------------------------------------------------------------


def test_gateway_runs_only_while_enabled(monkeypatch, synth):
    monkeypatch.undo()  # real start_gateway for this test
    monkeypatch.setattr(cloning_engine, "synthesize", lambda *a, **k: wav_bytes())
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("VOXWELL_PHONE_PORT", str(port))
    url = f"http://127.0.0.1:{port}/twilio/greeting/{'0' * 32}.wav"
    try:
        settings(enabled=True)
        deadline = time.time() + 10
        while not phone.gateway_running() and time.time() < deadline:
            time.sleep(0.05)
        assert phone.gateway_running()
        with pytest.raises(urllib.error.HTTPError) as err:  # up, and refusing a guessed link
            urllib.request.urlopen(url, timeout=5)
        assert err.value.code == 404
    finally:
        settings(enabled=False, auth_token=None)
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
        except urllib.error.HTTPError:
            time.sleep(0.05)
            continue
        except (urllib.error.URLError, ConnectionError):
            break
    else:
        pytest.fail("the gateway kept running after phone calls were turned off")
