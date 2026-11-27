"""The server marks what it sends out, with the speech and watermark models faked out."""

import io
import json

import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import app as server
import receipts
from conftest import SAMPLE_RATE, FakeWatermark, speechlike


class FakeModel:
    def generate(self, **kwargs):
        # Like OmniVoice.generate: one 1-D NumPy array per text.
        return [speechlike(1.0)]


class BrokenWatermark(FakeWatermark):
    def embed(self, audio, sample_rate, tag):
        raise RuntimeError("no watermark today")


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    voice_dir = data_dir / "voices" / "voice-1"
    voice_dir.mkdir(parents=True)
    (data_dir / "generations").mkdir()
    sf.write(voice_dir / "ref.wav", speechlike(1.0), SAMPLE_RATE)
    (voice_dir / "profile.json").write_text(json.dumps({"ref_text": "Reference."}))

    monkeypatch.setattr(server, "VOICES_DIR", data_dir / "voices")
    monkeypatch.setattr(server, "GENERATIONS_DIR", data_dir / "generations")
    monkeypatch.setattr(server, "marker", receipts.Marker(data_dir, watermark=FakeWatermark()))
    monkeypatch.setattr(server, "model", FakeModel())
    monkeypatch.setattr(server, "model_status", "ready")
    monkeypatch.setattr(server, "is_torchcodec_available", lambda: True)
    # No `with`: the startup hook would start loading the real model.
    return TestClient(server.app), data_dir


def check(wav_bytes, data_dir, tmp_path):
    path = tmp_path / "response.wav"
    path.write_bytes(wav_bytes)
    return receipts.verify_file(path, data_dir, watermark=FakeWatermark())


def test_generate_returns_a_marked_file_and_keeps_its_receipt(client, tmp_path):
    http, data_dir = client
    response = http.post("/api/generate", data={"text": "Hello.", "voice_id": "voice-1"})
    assert response.status_code == 200

    result = check(response.content, data_dir, tmp_path)
    assert result["verdict"] == "intact"
    assert result["receipt"]["ai_generated"] is True
    assert result["receipt"]["model"] == server.MODEL_ID

    receipt_id = response.headers["X-Generation-Id"]
    assert result["receipt"]["id"] == receipt_id
    assert (data_dir / "generations" / f"{receipt_id}.wav").read_bytes() == response.content
    assert (data_dir / "receipts" / f"{receipt_id}.json").exists()


def test_clone_preview_is_marked_too(client, tmp_path):
    http, data_dir = client
    buffer = io.BytesIO()
    sf.write(buffer, speechlike(1.0), SAMPLE_RATE, format="WAV")
    response = http.post(
        "/api/clone/test",
        data={"text": "Hello.", "ref_text": "Reference."},
        files={"ref_audio": ("ref.wav", buffer.getvalue(), "audio/wav")},
    )
    assert response.status_code == 200
    assert check(response.content, data_dir, tmp_path)["verdict"] == "intact"


def test_no_audio_leaves_the_server_when_marking_fails(client, monkeypatch):
    http, data_dir = client
    monkeypatch.setattr(
        server, "marker", receipts.Marker(data_dir, watermark=BrokenWatermark())
    )
    response = http.post("/api/generate", data={"text": "Hello.", "voice_id": "voice-1"})
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert list((data_dir / "generations").iterdir()) == []


# ── Who may talk to the server ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "host, status",
    [
        ("localhost:8000", 200),
        ("127.0.0.1:8000", 200),
        ("LOCALHOST", 200),
        ("[::1]:8000", 200),
        # A name that someone else pointed at this machine.
        ("rebind.example.com:8000", 400),
        ("localhost.example.com", 400),
        ("127.0.0.1.example.com:8000", 400),
        ("[::1].example.com", 400),
        ("localhost:8000:example.com", 400),
        ("example.com:localhost", 400),
        ("", 400),
    ],
)
def test_the_server_only_answers_under_its_own_name(client, host, status):
    http, _ = client
    for path in ("/api/voices", "/api/voices/voice-1/audio", "/"):
        assert http.get(path, headers={"host": host}).status_code == status
    if status == 400:
        assert "OMNISUITE_ALLOWED_HOSTS" in http.get("/api/voices", headers={"host": host}).json()["error"]


def test_more_names_can_be_allowed(client, monkeypatch):
    http, _ = client
    assert http.get("/api/status", headers={"host": "studio.lan:8000"}).status_code == 400
    monkeypatch.setattr(server, "ALLOWED_HOSTS", server.ALLOWED_HOSTS | {"studio.lan"})
    assert http.get("/api/status", headers={"host": "studio.lan:8000"}).status_code == 200


@pytest.mark.parametrize(
    "origin, status",
    [
        (None, 200),
        ("http://localhost:8000", 200),
        ("http://LOCALHOST:8000", 200),
        # Another website, another program on this machine, a sandboxed frame.
        ("https://example.com", 403),
        ("http://localhost:3000", 403),
        ("http://localhost", 403),
        ("null", 403),
    ],
)
def test_a_request_from_another_website_is_turned_down(client, origin, status):
    http, data_dir = client
    headers = {"host": "localhost:8000"}
    if origin is not None:
        headers["origin"] = origin
    response = http.post(
        "/api/generate", data={"text": "Hello.", "voice_id": "voice-1"}, headers=headers
    )
    assert response.status_code == status
    if status == 403:
        assert list((data_dir / "generations").iterdir()) == []
