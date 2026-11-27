"""OmniSuite - Simple voice synthesis & cloning server."""

import asyncio
import datetime
import hashlib
import json
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import enrolment
import receipts
from runtime_config import (
    describe_torch_runtime,
    get_torch_runtime_config,
    is_torchcodec_available,
)

# ── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
VOICES_DIR = DATA_DIR / "voices"
GENERATIONS_DIR = DATA_DIR / "generations"
MODELS_DIR = DATA_DIR / "models"

for d in [VOICES_DIR, GENERATIONS_DIR, MODELS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def voice_path(voice_id: str) -> Path | None:
    """Directory of a voice, or None when the id would point outside VOICES_DIR."""
    base = os.path.normpath(os.path.abspath(VOICES_DIR))
    full = os.path.normpath(os.path.join(base, voice_id))
    # Only direct children of VOICES_DIR: no "..", no absolute paths, no nested dirs.
    if not full.startswith(base + os.sep) or os.path.dirname(full) != base:
        return None
    return Path(full)

# ── Default voices ───────────────────────────────────────────────────────────

DEFAULT_VOICES = [
    {
        "id": "default-alex",
        "name": "Alex",
        "language": "en",
        "type": "default",
        "description": "Neutral male narrator",
    },
    {
        "id": "default-sarah",
        "name": "Sarah",
        "language": "en",
        "type": "default",
        "description": "Warm conversational female",
    },
    {
        "id": "default-hans",
        "name": "Hans",
        "language": "de",
        "type": "default",
        "description": "Calm measured male",
    },
    {
        "id": "default-lucia",
        "name": "Lucia",
        "language": "es",
        "type": "default",
        "description": "Bright expressive female",
    },
    {
        "id": "default-yuki",
        "name": "Yuki",
        "language": "ja",
        "type": "default",
        "description": "Clear professional female",
    },
    {
        "id": "default-pierre",
        "name": "Pierre",
        "language": "fr",
        "type": "default",
        "description": "Refined formal male",
    },
    {
        "id": "default-priya",
        "name": "Priya",
        "language": "hi",
        "type": "default",
        "description": "Friendly articulate female",
    },
    {
        "id": "default-marco",
        "name": "Marco",
        "language": "it",
        "type": "default",
        "description": "Expressive Italian male",
    },
]

# ── Engine ───────────────────────────────────────────────────────────────────

MODEL_ID = "k2-fsa/OmniVoice"

model = None
model_status = "not_loaded"  # not_loaded | loading | ready | error
model_error = None
torch_runtime = get_torch_runtime_config()
# Watermarks and signs every file that leaves generate_audio.
marker = receipts.Marker(DATA_DIR)
# Sentences handed out for enrolment that nobody has read back yet.
challenges = enrolment.Challenges()
asr_loaded = False
asr_lock = threading.Lock()


def load_model():
    """Load OmniVoice model. Called once at startup."""
    global model, model_status, model_error
    model_status = "loading"
    try:
        from omnivoice import OmniVoice

        model = OmniVoice.from_pretrained(
            MODEL_ID,
            device_map=torch_runtime.device_map,
            dtype=torch_runtime.dtype,
        )
        # Not ready until files can be marked: no unmarked audio leaves the server.
        marker.load()
        model_status = "ready"
        print(f"Model loaded ({describe_torch_runtime(torch_runtime)})")
    except Exception as e:
        model_status = "error"
        # Details stay in the server console; the status endpoint only reports a failure.
        model_error = "Model failed to load. See the server console for details."
        print(f"Model load failed: {e}")


TORCHCODEC_MISSING = (
    "TorchCodec is required for reference audio decoding. "
    "Install the 'torchcodec' dependency and restart OmniSuite."
)


class TorchCodecMissingError(RuntimeError):
    """Reference audio needs TorchCodec, which isn't installed."""


def write_temp_wav(content: bytes) -> str:
    """Write uploaded audio to a temporary .wav file and return its path."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(content)
        return tmp.name


def generation_error(e: Exception) -> JSONResponse:
    """500 response for a failed generation: known causes by name, the rest only in the log."""
    if isinstance(e, TorchCodecMissingError):
        return JSONResponse(status_code=500, content={"error": TORCHCODEC_MISSING})
    print(f"Generation failed: {e!r}")
    return JSONResponse(
        status_code=500,
        content={"error": "Generation failed. See the server console for details."},
    )


def transcribe(audio: np.ndarray, sample_rate: int) -> str:
    """What Whisper hears in a recording. Loads Whisper the first time."""
    global asr_loaded
    with asr_lock:
        if not asr_loaded:
            model.load_asr_model()
            asr_loaded = True
        return model.transcribe((audio, sample_rate))


def voice_claim(voice_dir: Path, profile: dict) -> dict:
    """How a voice got here, for the receipt of a file that speaks with it.

    "read-aloud" only while the reference clip is still the take that passed.
    """
    claim = {"id": profile.get("id", voice_dir.name), "enrolment": "none"}
    enrolled = profile.get("enrolment")
    if isinstance(enrolled, dict) and enrolled.get("method") == "read-aloud":
        try:
            clip = hashlib.sha256((voice_dir / "ref.wav").read_bytes()).hexdigest()
        except OSError:
            return claim
        if clip == enrolled.get("ref_sha256"):
            claim["enrolment"] = "read-aloud"
    return claim


def generate_audio(
    text: str,
    ref_audio_path: str,
    ref_text: str,
    speed: float = 1.0,
    voice: dict | None = None,
) -> tuple[bytes, dict]:
    """Generate speech, return the marked WAV bytes and their receipt."""
    if model is None:
        raise RuntimeError("Model not loaded")

    if ref_audio_path and not is_torchcodec_available():
        raise TorchCodecMissingError(TORCHCODEC_MISSING)

    audio = model.generate(
        text=text,
        ref_audio=ref_audio_path,
        # Never None: generate() would then load Whisper on its own to transcribe the clip.
        ref_text=ref_text or "",
        speed=speed,
        preprocess_prompt=False,
    )

    # Watermark, encode as WAV (soundfile, no ffmpeg needed) and sign
    # generate() returns one NumPy array per text.
    audio_np = np.asarray(audio[0])
    return marker.mark(audio_np, 24000, model=MODEL_ID, text=text, voice=voice)


# ── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(title="OmniSuite")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
async def status():
    return {
        "status": model_status,
        "error": model_error,
        "device": torch_runtime.device_map,
        "dtype": str(torch_runtime.dtype).replace("torch.", ""),
        "acceleration": torch_runtime.acceleration,
        "dependencies": {
            "torchcodec": is_torchcodec_available(),
        },
    }


@app.get("/api/voices")
async def list_voices():
    voices = list(DEFAULT_VOICES)

    # Add cloned voices from disk
    for voice_dir in VOICES_DIR.iterdir():
        profile_path = voice_dir / "profile.json"
        if profile_path.exists():
            try:
                profile = json.loads(profile_path.read_text())
                claim = voice_claim(voice_dir, profile)
                profile["enrolled"] = claim["enrolment"] == "read-aloud"
                voices.append(profile)
            except Exception:
                pass

    return voices


@app.post("/api/generate")
async def generate(
    text: str = Form(...),
    voice_id: str = Form(...),
    speed: float = Form(1.0),
):
    if model_status != "ready":
        return JSONResponse(status_code=503, content={"error": "Model not loaded"})

    # Find voice
    voice_dir = voice_path(voice_id)
    ref_wav = voice_dir / "ref.wav" if voice_dir else None
    profile_path = voice_dir / "profile.json" if voice_dir else None

    if ref_wav is None or profile_path is None or not ref_wav.exists():
        return JSONResponse(
            status_code=404, content={"error": f"Voice '{voice_id}' not found"}
        )

    profile = {}
    if profile_path.exists():
        profile = json.loads(profile_path.read_text())
    ref_text = profile.get("ref_text", "")

    try:
        wav_bytes, receipt = await asyncio.to_thread(
            generate_audio,
            text,
            str(ref_wav),
            ref_text,
            speed,
            voice_claim(voice_dir, profile),
        )
    except Exception as e:
        return generation_error(e)

    # Save to generations, under the id of the receipt
    gen_id = receipt["id"]
    gen_path = GENERATIONS_DIR / f"{gen_id}.wav"
    gen_path.write_bytes(wav_bytes)

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "X-Generation-Id": gen_id,
        },
    )


@app.post("/api/clone/test")
async def clone_test(
    ref_audio: UploadFile = File(...),
    ref_text: str = Form(""),
    text: str = Form(...),
    speed: float = Form(1.0),
):
    if model_status != "ready":
        return JSONResponse(status_code=503, content={"error": "Model not loaded"})

    content = await ref_audio.read()
    tmp_path = await asyncio.to_thread(write_temp_wav, content)

    try:
        wav_bytes, _receipt = await asyncio.to_thread(
            generate_audio, text, tmp_path, ref_text, speed, {"enrolment": "none"}
        )
        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception as e:
        return generation_error(e)
    finally:
        os.unlink(tmp_path)


@app.post("/api/clone/save")
async def clone_save(
    ref_audio: UploadFile = File(...),
    ref_text: str = Form(""),
    name: str = Form(...),
    language: str = Form("en"),
):
    voice_id = str(uuid.uuid4())
    voice_dir = VOICES_DIR / voice_id
    voice_dir.mkdir(parents=True, exist_ok=True)

    # Save ref audio
    ref_path = voice_dir / "ref.wav"
    content = await ref_audio.read()
    ref_path.write_bytes(content)

    # Save profile
    profile = {
        "id": voice_id,
        "name": name,
        "type": "cloned",
        "language": language,
        "ref_text": ref_text,
        "description": f"Cloned voice: {name}",
    }
    (voice_dir / "profile.json").write_text(json.dumps(profile, indent=2))

    return profile


@app.post("/api/enrol/start")
async def enrol_start(language: str = Form("en")):
    """Make up a sentence for someone to read aloud."""
    if model_status != "ready":
        return JSONResponse(status_code=503, content={"error": "Model not loaded"})
    if language not in enrolment.LANGUAGES:
        return JSONResponse(
            status_code=400,
            content={"error": "Sentences are available in English and German."},
        )
    challenge = challenges.start(language)
    return {
        "challenge_id": challenge.id,
        "sentence": challenge.sentence,
        "language": challenge.language,
        "expires_in": enrolment.CHALLENGE_SECONDS,
        "max_seconds": enrolment.RECORD_SECONDS,
    }


@app.post("/api/enrol/finish")
async def enrol_finish(
    take: UploadFile = File(...),
    challenge_id: str = Form(...),
    name: str = Form(...),
):
    """Check a reading of the sentence. If the words fit, it becomes a voice."""
    if model_status != "ready":
        return JSONResponse(status_code=503, content={"error": "Model not loaded"})
    name = name.strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "Give the voice a name."})
    if len(name) > enrolment.MAX_NAME_LENGTH:
        return JSONResponse(status_code=400, content={"error": "That name is too long."})

    try:
        audio, sample_rate = enrolment.read_take(
            await take.read(enrolment.MAX_TAKE_BYTES + 1)
        )
    except enrolment.TakeError as error:
        return JSONResponse(status_code=400, content={"error": str(error)})

    challenge = challenges.claim(challenge_id)
    if challenge is None:
        return JSONResponse(
            status_code=410,
            content={"error": "That sentence has expired. Get a new one."},
        )
    try:
        heard = await asyncio.to_thread(transcribe, audio, sample_rate)
    except Exception as e:
        challenges.give_back(challenge, used_a_try=False)
        print(f"Transcription failed: {e!r}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "The recording could not be checked. "
                "See the server console for details."
            },
        )

    fits, score = enrolment.matches(challenge.sentence, heard)
    if not fits:
        tries_left = challenges.give_back(challenge)
        return JSONResponse(
            status_code=422,
            content={
                "error": "That did not match the sentence. Read it once more."
                if tries_left
                else "That did not match the sentence. Get a new one and try again.",
                "heard": heard,
                "tries_left": tries_left,
            },
        )

    voice_id = str(uuid.uuid4())
    voice_dir = VOICES_DIR / voice_id
    voice_dir.mkdir(parents=True, exist_ok=True)
    clip = enrolment.reference_wav(audio, sample_rate)
    (voice_dir / "ref.wav").write_bytes(clip)
    profile = {
        "id": voice_id,
        "name": name,
        "type": "cloned",
        "language": challenge.language,
        "ref_text": challenge.sentence,
        "description": f"Cloned voice: {name}",
        "enrolment": {
            "method": "read-aloud",
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(
                timespec="seconds"
            ),
            "score": score,
            "ref_sha256": hashlib.sha256(clip).hexdigest(),
        },
    }
    (voice_dir / "profile.json").write_text(json.dumps(profile, indent=2))
    return {**profile, "enrolled": True}


@app.delete("/api/voices/{voice_id}")
async def delete_voice(voice_id: str):
    voice_dir = voice_path(voice_id)
    if voice_dir and voice_dir.exists():
        shutil.rmtree(voice_dir)
        return {"ok": True}
    return JSONResponse(status_code=404, content={"error": "Not found"})


@app.get("/api/voices/{voice_id}/audio")
async def get_voice_audio(voice_id: str):
    voice_dir = voice_path(voice_id)
    ref_wav = voice_dir / "ref.wav" if voice_dir else None
    if ref_wav is None or not ref_wav.exists():
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return FileResponse(ref_wav, media_type="audio/wav")


# ── Startup ──────────────────────────────────────────────────────────────────


@app.on_event("startup")
async def startup():
    threading.Thread(target=load_model, daemon=True).start()
