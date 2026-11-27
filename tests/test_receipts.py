"""Marking and verifying, with the watermark model faked out."""

import io
import json
import os

import pytest
import soundfile as sf

import receipts
from conftest import SAMPLE_RATE, FakeWatermark, speechlike


def make_file(marker, tmp_path, name="clip.wav", text="Hello there."):
    wav_bytes, receipt = marker.mark(
        speechlike(1.0), SAMPLE_RATE, model="test/model", text=text
    )
    path = tmp_path / name
    path.write_bytes(wav_bytes)
    return path, receipt


def verify(path, marker, **kwargs):
    data_dir = marker.keys_dir.parent
    return receipts.verify_file(path, data_dir, watermark=FakeWatermark(), **kwargs)


def test_tag_is_stable_and_16_bit():
    tag = receipts.tag_for("5d0c0b9e-0000-4000-8000-000000000000")
    assert tag == receipts.tag_for("5d0c0b9e-0000-4000-8000-000000000000")
    assert 0 <= tag < 2**16
    assert len(receipts.format_tag(tag)) == 4


def test_keys_are_created_once_and_reused(tmp_path):
    keys_dir = tmp_path / "keys"
    first = receipts.load_signing_keys(keys_dir)
    second = receipts.load_signing_keys(keys_dir)
    assert first == second
    assert first.name.startswith("OmniSuite install ")
    if os.name == "posix":
        assert (keys_dir / "signer.key").stat().st_mode & 0o777 == 0o600


def test_incomplete_keys_are_not_silently_replaced(tmp_path):
    keys_dir = tmp_path / "keys"
    receipts.load_signing_keys(keys_dir)
    (keys_dir / "signer.key").unlink()
    with pytest.raises(RuntimeError, match="incomplete"):
        receipts.load_signing_keys(keys_dir)


def test_marked_file_still_plays_and_has_a_receipt(marker, tmp_path):
    path, receipt = make_file(marker, tmp_path, text="A private sentence.")
    audio, sample_rate = sf.read(path)
    assert sample_rate == SAMPLE_RATE
    assert len(audio) == SAMPLE_RATE

    stored = json.loads((marker.receipts_dir / f"{receipt['id']}.json").read_text())
    assert stored == receipt
    assert stored["audio"]["seconds"] == 1.0
    assert stored["watermark"]["tag"] == receipts.format_tag(receipts.tag_for(receipt["id"]))
    # The text stays on this machine: a hash in the receipt, nothing in the file.
    assert "A private sentence." not in json.dumps(stored)
    assert b"A private sentence." not in path.read_bytes()


def test_stereo_input_is_marked_per_channel(marker):
    stereo = [speechlike(0.5), speechlike(0.5, seed=1)]
    wav_bytes, _ = marker.mark(stereo, SAMPLE_RATE, model="test/model")
    audio, _ = sf.read(io.BytesIO(wav_bytes))
    assert audio.shape == (SAMPLE_RATE // 2, 2)


def test_own_file_is_intact(marker, tmp_path):
    path, receipt = make_file(marker, tmp_path)
    result = verify(path, marker)
    assert result["verdict"] == "intact"
    assert result["receipt"]["state"] == "trusted"
    assert result["receipt"]["signed_here"] is True
    assert result["receipt"]["ai_generated"] is True
    assert result["receipt"]["id"] == receipt["id"]
    assert result["receipt"]["model"] == "test/model"
    assert result["watermark"]["found"] is True
    assert result["watermark"]["matches_receipt"] is True


def test_file_from_another_install_needs_its_root_to_be_trusted(marker, tmp_path):
    path, _ = make_file(marker, tmp_path)
    other = receipts.Marker(tmp_path / "other", watermark=FakeWatermark())
    other.load()

    unknown = verify(path, other)
    assert unknown["verdict"] == "untrusted"
    assert unknown["receipt"]["state"] == "valid"
    assert unknown["receipt"]["signed_here"] is False

    trusted = verify(path, other, trust=[marker.keys_dir / "root.pem"])
    assert trusted["verdict"] == "intact"
    assert trusted["receipt"]["state"] == "trusted"
    assert trusted["receipt"]["signed_here"] is False


def test_copied_serial_number_does_not_pass_as_this_install(marker, tmp_path, monkeypatch):
    serial = int(marker.load().serial)
    monkeypatch.setattr(receipts.x509, "random_serial_number", lambda: serial)
    impostor = receipts.Marker(tmp_path / "impostor", watermark=FakeWatermark())
    path, _ = make_file(impostor, tmp_path)
    assert impostor.load().serial == marker.load().serial

    result = verify(path, marker)
    assert result["verdict"] == "untrusted"
    assert result["receipt"]["state"] == "valid"
    assert result["receipt"]["signed_here"] is False


def test_text_from_a_file_cannot_drive_the_terminal():
    result = {
        "file": "clip.wav",
        "verdict": "untrusted",
        "receipt": {
            "state": "valid",
            "id": "id\x1b[2K",
            "created": "now",
            "model": "model\r",
            "tag": None,
            "ai_generated": True,
            "signer": "Mallory\x1b[1A\x1b[2K",
            "signed_here": False,
            "problems": [],
        },
        "watermark": {"found": False, "score": 0.0},
    }
    text = receipts._describe(result)
    assert "\x1b" not in text and "\r" not in text
    assert "unknown to this install" in text


def test_changed_audio_breaks_the_receipt(marker, tmp_path):
    path, _ = make_file(marker, tmp_path)
    data = bytearray(path.read_bytes())
    data[2000] ^= 0xFF  # inside the audio samples
    path.write_bytes(data)
    result = verify(path, marker)
    assert result["verdict"] == "broken"
    assert "assertion.dataHash.mismatch" in result["receipt"]["problems"]


def test_damaged_manifest_breaks_the_receipt(marker, tmp_path):
    path, _ = make_file(marker, tmp_path)
    data = bytearray(path.read_bytes())
    data[data.find(b"jumb") + 200] ^= 0xFF
    path.write_bytes(data)
    result = verify(path, marker)
    assert result["verdict"] == "broken"
    assert result["receipt"]["problems"]


def test_manifest_damaged_at_its_start_breaks_the_receipt(marker, tmp_path):
    path, _ = make_file(marker, tmp_path)
    data = bytearray(path.read_bytes())
    # The box that holds the manifest itself: without it c2pa finds no provenance.
    inner = data.find(b"jumb", data.find(b"jumb") + 4)
    data[inner : inner + 4] = b"xxxx"
    path.write_bytes(data)
    result = verify(path, marker)
    assert result["verdict"] == "broken"
    assert result["receipt"]["signer"] is None
    assert "damaged, could not be read" in receipts._describe(result)


def test_file_cut_off_inside_the_manifest_breaks_the_receipt(marker, tmp_path):
    path, _ = make_file(marker, tmp_path)
    data = path.read_bytes()
    path.write_bytes(data[: data.find(b"jumb") + 300])
    assert verify(path, marker)["verdict"] == "broken"


def test_manifest_chunk_is_only_looked_for_in_wav_files(tmp_path):
    for name, content in {
        "empty.wav": b"",
        "short.wav": b"RIFF\x04\x00\x00\x00WAVE",
        "text.wav": b"C2PA is mentioned here, but this is no WAV file.",
        "odd.wav": b"RIFF\x00\x00\x00\x00WAVEjunk\x03\x00\x00\x00abc\x00C2PA\x00\x00\x00\x00",
    }.items():
        path = tmp_path / name
        path.write_bytes(content)
        assert receipts._has_manifest_chunk(path) is (name == "odd.wav")
    assert receipts._has_manifest_chunk(tmp_path / "missing.wav") is False


def test_watermark_survives_when_the_manifest_is_gone(marker, tmp_path):
    path, receipt = make_file(marker, tmp_path)
    audio, sample_rate = sf.read(path, dtype="int16")
    stripped = tmp_path / "stripped.wav"
    sf.write(stripped, audio, sample_rate, subtype="PCM_16")  # drops the manifest

    result = verify(stripped, marker)
    assert result["verdict"] == "stripped"
    assert result["receipt"] is None
    assert result["watermark"]["tag"] == receipt["watermark"]["tag"]
    assert result["watermark"]["receipts_here"] == [
        {"id": receipt["id"], "created": receipt["created"]}
    ]


def test_plain_audio_is_unmarked(marker, tmp_path):
    plain = tmp_path / "plain.wav"
    sf.write(plain, speechlike(1.0), SAMPLE_RATE, subtype="PCM_16")
    result = verify(plain, marker)
    assert result["verdict"] == "unmarked"
    assert result["receipt"] is None
    assert result["watermark"]["found"] is False


def test_unreadable_audio_is_reported_not_raised(marker, tmp_path):
    junk = tmp_path / "notes.txt"
    junk.write_text("not audio")
    result = verify(junk, marker)
    assert result["verdict"] == "unmarked"
    assert result["watermark"]["found"] is None
    assert "error" in result["watermark"]


@pytest.fixture
def cli(marker, monkeypatch):
    monkeypatch.setattr(receipts, "DATA_DIR", marker.keys_dir.parent)
    monkeypatch.setattr(receipts, "AudioSealWatermark", FakeWatermark)
    return receipts.main


def test_cli_exit_codes(cli, marker, tmp_path, capsys):
    path, receipt = make_file(marker, tmp_path)
    assert cli(["verify", str(path)]) == 0
    out = capsys.readouterr().out
    assert "AI-generated, receipt intact" in out
    assert "signed by this install" in out
    assert receipt["id"] in out

    audio, sample_rate = sf.read(path, dtype="int16")
    stripped = tmp_path / "stripped.wav"
    sf.write(stripped, audio, sample_rate, subtype="PCM_16")
    assert cli(["verify", str(stripped)]) == 3
    out = capsys.readouterr().out
    assert "watermarked as AI-generated, no receipt in the file" in out
    assert f"made here: {receipt['id']}" in out

    data = bytearray(path.read_bytes())
    data[2000] ^= 0xFF
    path.write_bytes(data)
    assert cli(["verify", str(path)]) == 4

    plain = tmp_path / "plain.wav"
    sf.write(plain, speechlike(1.0), SAMPLE_RATE, subtype="PCM_16")
    assert cli(["verify", str(plain)]) == 5
    assert "does not prove" in capsys.readouterr().out

    assert cli(["verify", str(tmp_path / "missing.wav")]) == 1


def test_cli_does_not_pass_a_file_signed_by_a_stranger(cli, tmp_path, capsys):
    stranger = receipts.Marker(tmp_path / "stranger", watermark=FakeWatermark())
    path, _ = make_file(stranger, tmp_path)
    assert cli(["verify", str(path)]) == 6
    out = capsys.readouterr().out
    assert "marked as AI-generated, by a signer unknown to this install" in out
    assert "--trust" in out

    root = str(stranger.keys_dir / "root.pem")
    assert cli(["verify", "--trust", root, str(path)]) == 0
    assert "AI-generated, receipt intact" in capsys.readouterr().out


def test_cli_json(cli, marker, tmp_path, capsys):
    path, receipt = make_file(marker, tmp_path)
    assert cli(["verify", "--json", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["verdict"] == "intact"
    assert result["receipt"]["id"] == receipt["id"]
