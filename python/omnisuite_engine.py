"""OmniSuite embedded engine — CPU-only OmniVoice inference for PyO3."""

import io
import logging
import tempfile

logger = logging.getLogger("omnisuite_engine")

_model = None
_model_loaded = False
_loading_progress = 0.0
_loading_error = None


def load_model(model_path: str, progress_callback=None) -> None:
    """Load OmniVoice model from a local directory."""
    global _model, _model_loaded, _loading_progress, _loading_error
    try:
        import torch
        import torchaudio  # noqa: ensure available

        logger.info("Loading OmniVoice model from %s ...", model_path)
        _loading_progress = 0.1
        if progress_callback:
            progress_callback(0.1)

        from omnivoice import OmniVoice

        _loading_progress = 0.3
        if progress_callback:
            progress_callback(0.3)

        _model = OmniVoice.from_pretrained(
            model_path,
            device_map="cpu",
            dtype=torch.float32,
        )

        _loading_progress = 0.9
        if progress_callback:
            progress_callback(0.9)

        _model_loaded = True
        _loading_progress = 1.0
        _loading_error = None
        if progress_callback:
            progress_callback(1.0)

        logger.info("Model loaded successfully (CPU)")

    except Exception as e:
        _model_loaded = False
        _loading_error = str(e)
        logger.error("Failed to load model: %s", e)
        raise


def generate(
    text: str,
    ref_audio_bytes: bytes,
    ref_text: str,
    language: str = "",
    num_steps: int = 32,
    speed: float = 1.0,
) -> bytes:
    """Generate speech. Returns WAV bytes at 24kHz."""
    import torch
    import torchaudio

    if not _model_loaded or _model is None:
        raise RuntimeError("Model not loaded")

    # OmniVoice API requires a file path for ref_audio, so write to temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        tmp.write(ref_audio_bytes)
        tmp.flush()

        kwargs = {
            "text": text,
            "ref_audio": tmp.name,
            "ref_text": ref_text,
            "num_step": num_steps,
            "speed": speed,
        }

        audio = _model.generate(**kwargs)

    # Convert tensor to WAV bytes
    buf = io.BytesIO()
    torchaudio.save(buf, audio[0].cpu(), 24000, format="wav")
    buf.seek(0)
    return buf.read()


def unload_model() -> None:
    """Unload the model and free memory."""
    global _model, _model_loaded, _loading_progress
    _model = None
    _model_loaded = False
    _loading_progress = 0.0
    import gc
    gc.collect()


def is_loaded() -> bool:
    return _model_loaded


def get_status() -> dict:
    return {
        "loaded": _model_loaded,
        "progress": _loading_progress,
        "error": _loading_error,
    }
