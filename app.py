"""OmniSuite — Simple voice synthesis & cloning server."""

import asyncio
import io
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import torch
import torchaudio
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# ── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
VOICES_DIR = DATA_DIR / "voices"
GENERATIONS_DIR = DATA_DIR / "generations"
MODELS_DIR = DATA_DIR / "models"

for d in [VOICES_DIR, GENERATIONS_DIR, MODELS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Default voices ───────────────────────────────────────────────────────────

DEFAULT_VOICES = [
    {"id": "default-alex", "name": "Alex", "language": "en", "type": "default", "description": "Neutral male narrator"},
    {"id": "default-sarah", "name": "Sarah", "language": "en", "type": "default", "description": "Warm conversational female"},
    {"id": "default-hans", "name": "Hans", "language": "de", "type": "default", "description": "Calm measured male"},
    {"id": "default-lucia", "name": "Lucia", "language": "es", "type": "default", "description": "Bright expressive female"},
    {"id": "default-yuki", "name": "Yuki", "language": "ja", "type": "default", "description": "Clear professional female"},
    {"id": "default-pierre", "name": "Pierre", "language": "fr", "type": "default", "description": "Refined formal male"},
    {"id": "default-priya", "name": "Priya", "language": "hi", "type": "default", "description": "Friendly articulate female"},
    {"id": "default-marco", "name": "Marco", "language": "it", "type": "default", "description": "Expressive Italian male"},
]

# ── Engine ───────────────────────────────────────────────────────────────────

model = None
model_status = "not_loaded"  # not_loaded | loading | ready | error
model_error = None


def load_model():
    """Load OmniVoice model. Called once at startup."""
    global model, model_status, model_error
    model_status = "loading"
    try:
        from omnivoice import OmniVoice
        model = OmniVoice.from_pretrained(
            "k2-fsa/OmniVoice",
            device_map="cpu",
            dtype=torch.float32,
        )
        model_status = "ready"
        print("Model loaded (CPU)")
    except Exception as e:
        model_status = "error"
        model_error = str(e)
        print(f"Model load failed: {e}")


def generate_audio(text: str, ref_audio_path: str, ref_text: str, speed: float = 1.0) -> bytes:
    """Generate speech, return WAV bytes."""
    if model is None:
        raise RuntimeError("Model not loaded")

    audio = model.generate(
        text=text,
        ref_audio=ref_audio_path,
        ref_text=ref_text,
        speed=speed,
    )

    buf = io.BytesIO()
    torchaudio.save(buf, audio[0].cpu(), 24000, format="wav")
    buf.seek(0)
    return buf.read()


# ── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(title="OmniSuite")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
async def status():
    return {"status": model_status, "error": model_error}


@app.get("/api/voices")
async def list_voices():
    voices = list(DEFAULT_VOICES)

    # Add cloned voices from disk
    for voice_dir in VOICES_DIR.iterdir():
        profile_path = voice_dir / "profile.json"
        if profile_path.exists():
            try:
                profile = json.loads(profile_path.read_text())
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
    voice_dir = VOICES_DIR / voice_id
    ref_wav = voice_dir / "ref.wav"
    profile_path = voice_dir / "profile.json"

    if not ref_wav.exists():
        return JSONResponse(status_code=404, content={"error": f"Voice '{voice_id}' not found"})

    ref_text = ""
    if profile_path.exists():
        profile = json.loads(profile_path.read_text())
        ref_text = profile.get("ref_text", "")

    try:
        wav_bytes = await asyncio.to_thread(generate_audio, text, str(ref_wav), ref_text, speed)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

    # Save to generations
    gen_id = str(uuid.uuid4())
    gen_path = GENERATIONS_DIR / f"{gen_id}.wav"
    gen_path.write_bytes(wav_bytes)

    return Response(content=wav_bytes, media_type="audio/wav", headers={
        "X-Generation-Id": gen_id,
    })


@app.post("/api/clone/test")
async def clone_test(
    ref_audio: UploadFile = File(...),
    ref_text: str = Form(""),
    text: str = Form(...),
    speed: float = Form(1.0),
):
    if model_status != "ready":
        return JSONResponse(status_code=503, content={"error": "Model not loaded"})

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        content = await ref_audio.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        wav_bytes = await asyncio.to_thread(generate_audio, text, tmp_path, ref_text, speed)
        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
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


@app.delete("/api/voices/{voice_id}")
async def delete_voice(voice_id: str):
    voice_dir = VOICES_DIR / voice_id
    if voice_dir.exists():
        shutil.rmtree(voice_dir)
        return {"ok": True}
    return JSONResponse(status_code=404, content={"error": "Not found"})


@app.get("/api/voices/{voice_id}/audio")
async def get_voice_audio(voice_id: str):
    ref_wav = VOICES_DIR / voice_id / "ref.wav"
    if not ref_wav.exists():
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return FileResponse(ref_wav, media_type="audio/wav")


# ── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    import threading
    threading.Thread(target=load_model, daemon=True).start()
