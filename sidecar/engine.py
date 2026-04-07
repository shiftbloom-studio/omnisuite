import io
import logging
import torch
import torchaudio

logger = logging.getLogger(__name__)


class OmniVoiceEngine:
    """Wrapper around k2-fsa/OmniVoice model."""

    def __init__(self, device: str = "cuda:0"):
        self.device = device
        self.model = None
        self.model_loaded = False
        self.gpu_available = False
        self.gpu_name = None
        self.vram_total = None
        self.vram_used = None
        self.download_progress = 0.0
        self._detect_gpu()
        logger.info(f"OmniVoiceEngine initialized (device={device}, gpu={self.gpu_available})")

    def _detect_gpu(self):
        if torch.cuda.is_available():
            self.gpu_available = True
            self.gpu_name = torch.cuda.get_device_name(0)
            self.vram_total = torch.cuda.get_device_properties(0).total_memory
            self.vram_used = torch.cuda.memory_allocated(0)
        else:
            self.gpu_available = False
            self.device = "cpu"
            logger.warning("CUDA not available, falling back to CPU")

    def _update_vram(self):
        if self.gpu_available:
            self.vram_used = torch.cuda.memory_allocated(0)

    def load_model(self, progress_callback=None):
        """Load OmniVoice model from HuggingFace Hub."""
        try:
            logger.info("Loading OmniVoice model...")
            if progress_callback:
                progress_callback(0.1)

            from omnivoice import OmniVoice

            if progress_callback:
                progress_callback(0.3)

            dtype = torch.float16 if self.gpu_available else torch.float32
            self.model = OmniVoice.from_pretrained(
                "k2-fsa/OmniVoice",
                device_map=self.device,
                dtype=dtype,
            )

            if progress_callback:
                progress_callback(0.9)

            self.model_loaded = True
            self._update_vram()
            logger.info(f"Model loaded successfully on {self.device}")

            if progress_callback:
                progress_callback(1.0)

        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            self.model_loaded = False
            raise

    def generate(
        self,
        text: str,
        ref_audio_path: str,
        ref_text: str,
        language: str | None = None,
        num_step: int = 32,
        speed: float = 1.0,
    ) -> bytes:
        """Generate speech from text using a reference voice. Returns WAV bytes at 24kHz."""
        if not self.model_loaded:
            raise RuntimeError("Model not loaded")

        kwargs = {
            "text": text,
            "ref_audio": ref_audio_path,
            "ref_text": ref_text,
            "num_step": num_step,
            "speed": speed,
        }

        audio = self.model.generate(**kwargs)
        self._update_vram()
        return self._tensor_to_wav_bytes(audio[0])

    def design_voice(
        self,
        text: str,
        instruct: str,
        num_step: int = 32,
        speed: float = 1.0,
    ) -> bytes:
        """Generate speech with voice design via instruct text. Returns WAV bytes at 24kHz."""
        if not self.model_loaded:
            raise RuntimeError("Model not loaded")

        audio = self.model.generate(
            text=text,
            instruct=instruct,
            num_step=num_step,
            speed=speed,
        )
        self._update_vram()
        return self._tensor_to_wav_bytes(audio[0])

    def _tensor_to_wav_bytes(self, tensor: torch.Tensor) -> bytes:
        """Convert audio tensor to WAV bytes at 24kHz."""
        buf = io.BytesIO()
        torchaudio.save(buf, tensor.cpu(), 24000, format="wav")
        buf.seek(0)
        return buf.read()

    def get_health(self) -> dict:
        self._update_vram()
        return {
            "model_loaded": self.model_loaded,
            "gpu_available": self.gpu_available,
            "gpu_name": self.gpu_name,
            "vram_total": self.vram_total,
            "vram_used": self.vram_used,
        }
