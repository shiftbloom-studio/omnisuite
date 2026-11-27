"""Enrolment by reading, with the speech models faked out."""

import io
import json

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import app as server
import enrolment
import receipts
from conftest import SAMPLE_RATE, FakeWatermark, speechlike

# ── Sentences ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("language", sorted(enrolment.LANGUAGES))
def test_sentences_differ_from_one_call_to_the_next(language):
    sentences = {enrolment.make_sentence(language) for _ in range(50)}
    assert len(sentences) > 45
    for sentence in sentences:
        assert sentence.endswith(".")
        assert 12 <= len(enrolment.words(sentence)) <= 30


def test_no_sentences_for_other_languages():
    with pytest.raises(ValueError):
        enrolment.make_sentence("fr")


def test_word_lists_hold_plain_words_only():
    phrases = [p for options in enrolment.ENGLISH.values() for p in options]
    for slot, options in enrolment.GERMAN.items():
        phrases += [" ".join(o) if slot == "action" else o for o in options]
    for phrase in phrases:
        # No digits, no apostrophes, no hyphens: nothing Whisper could write two ways.
        assert all(ch.isalpha() or ch == " " for ch in phrase), phrase
    for options in [*enrolment.ENGLISH.values(), *enrolment.GERMAN.values()]:
        assert len(options) == len(set(options)) == 16


# ── Matching ─────────────────────────────────────────────────────────────────

SENTENCE = (
    "Early this morning, the tired baker carried a heavy basket "
    "behind the old station, and nobody asked why."
)


def test_punctuation_and_capitals_do_not_count():
    heard = "early this morning the tired baker carried a heavy basket behind the old station and nobody asked why"
    assert enrolment.matches(SENTENCE, heard) == (True, 1.0)


def test_a_misheard_word_or_two_still_passes():
    heard = "Early this morning, the tired baker carried a heavy basket behind the cold station and nobody asked."
    fits, score = enrolment.matches(SENTENCE, heard)
    assert fits
    assert score == 0.89


def test_other_words_do_not_pass():
    assert enrolment.matches(SENTENCE, "")[0] is False
    assert enrolment.matches(SENTENCE, "Hello, this is a test of my voice.")[0] is False
    # Half of it is not enough either.
    assert enrolment.matches(SENTENCE, "Early this morning, the tired baker carried")[0] is False
    # The right words with a lot said around them do not pass.
    padded = f"So what I wanted to say is {SENTENCE} and that is all for today folks"
    assert enrolment.matches(SENTENCE, padded)[0] is False


def test_german_sharp_s_and_umlauts_compare_equal_to_themselves():
    sentence = "Der fleißige Kellner zählte die leeren Flaschen, und niemand fragte warum."
    assert enrolment.matches(sentence, "der fleissige Kellner zählte die leeren Flaschen und niemand fragte warum")[0]
    assert enrolment.words("Bäcker's Brücke") == ["bäckers", "brücke"]
    assert enrolment.words("Garten-Mauer - und so") == ["gartenmauer", "und", "so"]


def test_word_errors_counts_swaps_gaps_and_extras():
    assert enrolment.word_errors(["a", "b", "c"], ["a", "b", "c"]) == 0
    assert enrolment.word_errors(["a", "b", "c"], ["a", "x", "c"]) == 1
    assert enrolment.word_errors(["a", "b", "c"], ["a", "c"]) == 1
    assert enrolment.word_errors(["a", "b", "c"], ["a", "b", "x", "c"]) == 1
    assert enrolment.word_errors(["a", "b", "c"], []) == 3
    assert enrolment.word_errors([], ["a"]) == 1


# ── Challenges ───────────────────────────────────────────────────────────────


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_a_sentence_can_be_claimed_once():
    open_sentences = enrolment.Challenges()
    challenge = open_sentences.start("en")
    assert open_sentences.claim(challenge.id) is challenge
    assert open_sentences.claim(challenge.id) is None
    assert open_sentences.claim("no-such-id") is None


def test_a_sentence_expires():
    clock = Clock()
    open_sentences = enrolment.Challenges(clock)
    challenge = open_sentences.start("de")
    clock.now += enrolment.CHALLENGE_SECONDS - 1
    assert open_sentences.claim(challenge.id) is challenge
    open_sentences.give_back(challenge)
    clock.now += 1
    assert open_sentences.claim(challenge.id) is None


def test_a_sentence_has_a_limited_number_of_tries():
    open_sentences = enrolment.Challenges()
    challenge = open_sentences.start("en")
    for tries_left in range(enrolment.MAX_ATTEMPTS - 1, 0, -1):
        claimed = open_sentences.claim(challenge.id)
        assert open_sentences.give_back(claimed) == tries_left
    claimed = open_sentences.claim(challenge.id)
    assert open_sentences.give_back(claimed) == 0
    assert open_sentences.claim(challenge.id) is None


def test_a_failed_check_that_was_not_the_readers_fault_costs_no_try():
    open_sentences = enrolment.Challenges()
    challenge = open_sentences.start("en")
    claimed = open_sentences.claim(challenge.id)
    assert open_sentences.give_back(claimed, used_a_try=False) == enrolment.MAX_ATTEMPTS


def test_only_so_many_sentences_wait_at_once():
    open_sentences = enrolment.Challenges()
    first = open_sentences.start("en")
    for _ in range(enrolment.MAX_OPEN_CHALLENGES):
        newest = open_sentences.start("en")
    assert open_sentences.claim(first.id) is None
    assert open_sentences.claim(newest.id) is newest


# ── Takes ────────────────────────────────────────────────────────────────────


def wav(seconds=4.0, channels=1, sample_rate=SAMPLE_RATE):
    audio = speechlike(seconds, sample_rate)
    if channels > 1:
        audio = np.stack([audio] * channels, axis=1)
    buffer = io.BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def test_a_take_is_read_as_mono():
    audio, sample_rate = enrolment.read_take(wav(4.0, channels=2, sample_rate=48000))
    assert sample_rate == 48000
    assert audio.shape == (4 * 48000,)
    assert audio.dtype == np.float32


@pytest.mark.parametrize(
    "content, message",
    [
        (b"not audio at all", "could not be read"),
        (wav(1.0), "too short"),
        (wav(enrolment.MAX_TAKE_SECONDS + 1, sample_rate=8000), "too long"),
        (b"\0" * (enrolment.MAX_TAKE_BYTES + 1), "too large"),
    ],
)
def test_unusable_takes_are_turned_down(content, message):
    with pytest.raises(enrolment.TakeError, match=message):
        enrolment.read_take(content)


def test_the_wait_before_and_after_the_words_is_cut():
    rng = np.random.default_rng(1)

    def hiss(seconds):
        return 0.0002 * rng.standard_normal(int(seconds * SAMPLE_RATE))

    take = np.concatenate([hiss(1.0), speechlike(4.0), hiss(1.5)]).astype(np.float32)
    buffer = io.BytesIO()
    sf.write(buffer, take, SAMPLE_RATE, format="WAV", subtype="PCM_16")

    audio, _ = enrolment.read_take(buffer.getvalue())
    kept = enrolment.KEPT_BEFORE_SECONDS + enrolment.KEPT_AFTER_SECONDS
    assert len(audio) / SAMPLE_RATE == pytest.approx(4.0 + kept, abs=0.05)
    # The words themselves are untouched.
    start = int((1.0 - enrolment.KEPT_BEFORE_SECONDS) * SAMPLE_RATE)
    assert np.allclose(audio, take[start : start + len(audio)], atol=1e-4)


def test_a_silent_take_is_turned_down():
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(5 * SAMPLE_RATE, dtype=np.float32), SAMPLE_RATE, format="WAV")
    with pytest.raises(enrolment.TakeError, match="nothing to hear"):
        enrolment.read_take(buffer.getvalue())


def test_a_take_may_run_a_moment_past_the_clock_of_the_page():
    seconds = enrolment.RECORD_SECONDS + 0.5
    audio, sample_rate = enrolment.read_take(wav(seconds, sample_rate=8000))
    assert len(audio) / sample_rate == pytest.approx(seconds, abs=0.05)


def test_a_take_at_an_absurd_sample_rate_is_turned_down():
    buffer = io.BytesIO()
    sf.write(buffer, speechlike(4.0), 1000, format="WAV", subtype="PCM_16")
    with pytest.raises(enrolment.TakeError, match="could not be read"):
        enrolment.read_take(buffer.getvalue())


def test_the_reference_clip_is_a_plain_wav():
    audio, sample_rate = enrolment.read_take(wav(4.0))
    clip, clip_rate = sf.read(io.BytesIO(enrolment.reference_wav(audio, sample_rate)))
    assert clip_rate == sample_rate
    assert clip.shape == audio.shape


# ── The server ───────────────────────────────────────────────────────────────


class FakeModel:
    """OmniVoice with a Whisper that hears whatever the test says."""

    def __init__(self):
        self.hears = ""
        self.whisper_loads = 0
        self.fails = False

    def load_asr_model(self):
        self.whisper_loads += 1

    def transcribe(self, audio):
        if self.whisper_loads == 0:
            raise RuntimeError("ASR model is not loaded.")
        if self.fails:
            raise RuntimeError("no whisper today")
        waveform, sample_rate = audio
        assert waveform.ndim == 1 and sample_rate > 0
        return self.hears

    def generate(self, **kwargs):
        # With None, OmniVoice would load Whisper itself, past the server's lock.
        assert isinstance(kwargs["ref_text"], str)
        return [speechlike(1.0)]


@pytest.fixture
def studio(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    (data_dir / "voices").mkdir(parents=True)
    (data_dir / "generations").mkdir()
    model = FakeModel()
    monkeypatch.setattr(server, "VOICES_DIR", data_dir / "voices")
    monkeypatch.setattr(server, "GENERATIONS_DIR", data_dir / "generations")
    monkeypatch.setattr(server, "marker", receipts.Marker(data_dir, watermark=FakeWatermark()))
    monkeypatch.setattr(server, "model", model)
    monkeypatch.setattr(server, "model_status", "ready")
    monkeypatch.setattr(server, "challenges", enrolment.Challenges())
    monkeypatch.setattr(server, "asr_loaded", False)
    monkeypatch.setattr(server, "is_torchcodec_available", lambda: True)
    # No `with`: the startup hook would start loading the real model.
    return TestClient(server.app), model, data_dir


def start(http, language="en"):
    response = http.post("/api/enrol/start", data={"language": language})
    assert response.status_code == 200
    return response.json()


def finish(http, challenge_id, take=None, name="Ada"):
    return http.post(
        "/api/enrol/finish",
        data={"challenge_id": challenge_id, "name": name},
        files={"take": ("take.wav", take or wav(4.0, sample_rate=48000), "audio/wav")},
    )


def verify(http, data_dir, tmp_path, voice_id):
    response = http.post("/api/generate", data={"text": "Hello.", "voice_id": voice_id})
    assert response.status_code == 200
    path = tmp_path / "out.wav"
    path.write_bytes(response.content)
    return receipts.verify_file(path, data_dir, watermark=FakeWatermark()), response


def test_start_hands_out_a_sentence(studio):
    http, _, _ = studio
    first, second = start(http, "de"), start(http, "de")
    assert first["language"] == "de"
    assert first["sentence"] != second["sentence"]
    assert first["challenge_id"] != second["challenge_id"]
    assert first["expires_in"] == enrolment.CHALLENGE_SECONDS
    # The page stops before the server would turn a take down.
    assert first["max_seconds"] < enrolment.MAX_TAKE_SECONDS


def test_start_turns_down_other_languages_and_waits_for_the_model(studio, monkeypatch):
    http, _, _ = studio
    assert http.post("/api/enrol/start", data={"language": "fr"}).status_code == 400
    monkeypatch.setattr(server, "model_status", "loading")
    assert http.post("/api/enrol/start", data={"language": "en"}).status_code == 503
    assert finish(http, "anything").status_code == 503


def test_reading_the_sentence_enrols_a_voice(studio):
    http, model, data_dir = studio
    challenge = start(http)
    model.hears = challenge["sentence"].lower().replace(",", "")
    take = wav(4.0, channels=2, sample_rate=48000)

    response = finish(http, challenge["challenge_id"], take, name="  Ada  ")
    assert response.status_code == 200
    voice = response.json()
    assert voice["name"] == "Ada"
    assert voice["type"] == "cloned"
    assert voice["language"] == "en"
    # The sentence is the transcript: nobody had to type it.
    assert voice["ref_text"] == challenge["sentence"]
    assert voice["enrolment"]["method"] == "read-aloud"
    assert voice["enrolment"]["score"] == 1.0

    voice_dir = data_dir / "voices" / voice["id"]
    clip, sample_rate = sf.read(voice_dir / "ref.wav")
    assert sample_rate == 48000 and clip.shape == (4 * 48000,)
    stored = json.loads((voice_dir / "profile.json").read_text())
    assert stored["enrolment"] == voice["enrolment"]

    listed = [v for v in http.get("/api/voices").json() if v["id"] == voice["id"]]
    assert listed[0]["enrolled"] is True

    # The sentence is used up.
    assert finish(http, challenge["challenge_id"]).status_code == 410


def test_other_words_do_not_enrol_a_voice(studio):
    http, model, data_dir = studio
    challenge = start(http)
    model.hears = "This is a clip from an old interview about something else."

    for tries_left in range(enrolment.MAX_ATTEMPTS - 1, -1, -1):
        response = finish(http, challenge["challenge_id"])
        assert response.status_code == 422
        assert response.json()["heard"] == model.hears
        assert response.json()["tries_left"] == tries_left
    assert "Get a new one" in response.json()["error"]

    model.hears = challenge["sentence"]
    assert finish(http, challenge["challenge_id"]).status_code == 410
    assert list((data_dir / "voices").iterdir()) == []


def test_a_take_that_cannot_be_used_costs_no_try(studio):
    http, model, _ = studio
    challenge = start(http)
    for content in (b"not audio", wav(1.0)):
        assert finish(http, challenge["challenge_id"], content).status_code == 400
    assert finish(http, challenge["challenge_id"], name="   ").status_code == 400
    too_long = "a" * (enrolment.MAX_NAME_LENGTH + 1)
    assert finish(http, challenge["challenge_id"], name=too_long).status_code == 400
    model.fails = True
    assert finish(http, challenge["challenge_id"]).status_code == 500
    model.fails = False

    model.hears = "something else entirely"
    response = finish(http, challenge["challenge_id"])
    assert response.json()["tries_left"] == enrolment.MAX_ATTEMPTS - 1


def test_whisper_is_loaded_once(studio):
    http, model, _ = studio
    for name in ("Ada", "Grace"):
        challenge = start(http)
        model.hears = challenge["sentence"]
        assert finish(http, challenge["challenge_id"], name=name).status_code == 200
    assert model.whisper_loads == 1


def test_receipt_says_the_voice_was_enrolled_by_reading(studio, tmp_path):
    http, model, data_dir = studio
    challenge = start(http)
    model.hears = challenge["sentence"]
    voice = finish(http, challenge["challenge_id"]).json()

    result, response = verify(http, data_dir, tmp_path, voice["id"])
    assert result["verdict"] == "intact"
    assert result["voice"] == {"enrolment": "read-aloud"}
    assert "voice      enrolled by reading a sentence aloud" in receipts._describe(result)

    receipt_id = response.headers["X-Generation-Id"]
    stored = json.loads((data_dir / "receipts" / f"{receipt_id}.json").read_text())
    assert stored["voice"] == {"id": voice["id"], "enrolment": "read-aloud"}
    # Which voice spoke stays on this machine.
    assert voice["id"].encode() not in response.content
    assert b"read-aloud" not in response.content


def test_receipt_says_so_when_the_voice_came_from_an_uploaded_clip(studio, tmp_path):
    http, _, data_dir = studio
    saved = http.post(
        "/api/clone/save",
        data={"name": "Clip", "ref_text": "Reference."},
        files={"ref_audio": ("ref.wav", wav(4.0), "audio/wav")},
    ).json()

    result, _ = verify(http, data_dir, tmp_path, saved["id"])
    assert result["voice"] == {"enrolment": "none"}
    assert "voice      not enrolled, taken from an uploaded clip" in receipts._describe(result)
    listed = [v for v in http.get("/api/voices").json() if v["id"] == saved["id"]]
    assert listed[0]["enrolled"] is False


def test_a_voice_without_a_transcript_does_not_make_the_model_transcribe(studio, tmp_path):
    http, _, data_dir = studio
    voice_dir = data_dir / "voices" / "by-hand"
    voice_dir.mkdir()
    (voice_dir / "ref.wav").write_bytes(wav(4.0))
    (voice_dir / "profile.json").write_text(json.dumps({"id": "by-hand", "ref_text": None}))

    result, _ = verify(http, data_dir, tmp_path, "by-hand")
    assert result["verdict"] == "intact"


def test_swapping_the_clip_afterwards_ends_the_enrolment(studio, tmp_path):
    http, model, data_dir = studio
    challenge = start(http)
    model.hears = challenge["sentence"]
    voice = finish(http, challenge["challenge_id"]).json()
    (data_dir / "voices" / voice["id"] / "ref.wav").write_bytes(wav(5.0))

    result, _ = verify(http, data_dir, tmp_path, voice["id"])
    assert result["voice"] == {"enrolment": "none"}
    listed = [v for v in http.get("/api/voices").json() if v["id"] == voice["id"]]
    assert listed[0]["enrolled"] is False


def test_a_voice_claim_is_only_read_for_files_signed_here(studio, tmp_path):
    http, model, data_dir = studio
    challenge = start(http)
    model.hears = challenge["sentence"]
    voice = finish(http, challenge["challenge_id"]).json()
    response = http.post("/api/generate", data={"text": "Hello.", "voice_id": voice["id"]})
    path = tmp_path / "out.wav"
    path.write_bytes(response.content)

    # Another install that happens to hold a receipt under the same id.
    other = receipts.Marker(tmp_path / "other", watermark=FakeWatermark())
    other.load()
    other.receipts_dir.mkdir(parents=True)
    receipt_id = response.headers["X-Generation-Id"]
    (other.receipts_dir / f"{receipt_id}.json").write_text(
        json.dumps({"voice": {"enrolment": "read-aloud"}})
    )
    result = receipts.verify_file(
        path,
        tmp_path / "other",
        trust=[data_dir / "keys" / "root.pem"],
        watermark=FakeWatermark(),
    )
    assert result["verdict"] == "intact"
    assert result["voice"] is None
    assert "  voice  " not in receipts._describe(result)
