"""The server marks what it sends out, with the speech and watermark models faked out."""

import io
import json

import pytest
import soundfile as sf
import torch
from fastapi.testclient import TestClient

import app as server
import receipts
from conftest import SAMPLE_RATE, FakeWatermark, speechlike


class FakeModel:
    def generate(self, **kwargs):
        return [torch.from_numpy(speechlike(1.0)).unsqueeze(0)]


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
