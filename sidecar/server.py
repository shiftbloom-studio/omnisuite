"""OmniSuite Python sidecar – FastAPI server for OmniVoice inference."""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from engine import OmniVoiceEngine

# ---------------------------------------------------------------------------
# Logging – everything goes to stderr so stdout is reserved for the PORT line
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine + loading state
# ---------------------------------------------------------------------------
engine = OmniVoiceEngine()

_loading_status = "starting"  # starting | downloading | loading | ready | error
_loading_progress = 0.0
_loading_error: str | None = None


def _load_model_background():
    """Load model in background thread so server stays responsive."""
    global _loading_status, _loading_progress, _loading_error
    try:
        _loading_status = "loading"

        def on_progress(p: float):
            global _loading_progress
            _loading_progress = p

        engine.load_model(progress_callback=on_progress)
        _loading_status = "ready"
        _loading_progress = 1.0
        logger.info("Model loaded, sidecar ready")
    except Exception as e:
        _loading_status = "error"
        _loading_error = str(e)
        logger.error(f"Model loading failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    thread = threading.Thread(target=_load_model_background, daemon=True)
    thread.start()
    yield


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="OmniSuite Sidecar", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    h = engine.get_health()
    return {
        "status": _loading_status,
        "model_loaded": h["model_loaded"],
        "gpu_available": h["gpu_available"],
        "gpu_name": h["gpu_name"],
        "vram_total": h["vram_total"],
        "vram_used": h["vram_used"],
        "progress": _loading_progress,
        "error": _loading_error,
    }


@app.post("/generate")
async def generate(
    text: str = Form(...),
    ref_audio: UploadFile = File(...),
    ref_text: str = Form(...),
    language: str = Form(None),
    num_step: int = Form(32),
    speed: float = Form(1.0),
):
    if not engine.model_loaded:
        return JSONResponse(status_code=503, content={"detail": "Model not loaded"})

    try:
        # Write uploaded ref audio to temp file (auto-cleanup)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            content = await ref_audio.read()
            tmp.write(content)
            tmp.flush()

            wav_bytes = engine.generate(
                text=text,
                ref_audio_path=tmp.name,
                ref_text=ref_text,
                language=language,
                num_step=num_step,
                speed=speed,
            )

        return Response(content=wav_bytes, media_type="audio/wav")

    except torch.cuda.OutOfMemoryError:
        return JSONResponse(status_code=507, content={"detail": "GPU out of memory. Try shorter text."})
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})


class DesignRequest(BaseModel):
    text: str
    instruct: str
    num_step: int = 32
    speed: float = 1.0


@app.post("/design/preview")
async def design_preview(req: DesignRequest):
    if not engine.model_loaded:
        return JSONResponse(status_code=503, content={"detail": "Model not loaded"})

    try:
        wav_bytes = engine.design_voice(
            text=req.text,
            instruct=req.instruct,
            num_step=req.num_step,
            speed=req.speed,
        )
        return Response(content=wav_bytes, media_type="audio/wav")

    except torch.cuda.OutOfMemoryError:
        return JSONResponse(status_code=507, content={"detail": "GPU out of memory."})
    except Exception as e:
        logger.error(f"Design preview failed: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})


# ---------------------------------------------------------------------------
# Main – parse port, start uvicorn, print PORT:<n> to stdout
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import torch  # noqa: needed for OOM catch above at module level
    import uvicorn

    parser = argparse.ArgumentParser(description="OmniSuite sidecar server")
    parser.add_argument("--port", type=int, default=0, help="Port to bind (0 = random)")
    args = parser.parse_args()

    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {"fmt": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"},
        },
        "handlers": {
            "stderr": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
                "formatter": "default",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
        },
    }

    if args.port == 0:
        # Use a socket to find a free port, then run uvicorn on it
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            actual_port = s.getsockname()[1]
        print(f"PORT:{actual_port}", flush=True)
        uvicorn.run(
            "server:app", host="127.0.0.1", port=actual_port, log_config=log_config,
        )
    else:
        print(f"PORT:{args.port}", flush=True)
        uvicorn.run("server:app", host="127.0.0.1", port=args.port, log_config=log_config)
