"""Test OmniVoice engine directly — no server needed."""

import io
import os
import tempfile
import time

from runtime_config import (
    describe_torch_runtime,
    get_torch_runtime_config,
    is_torchcodec_available,
)

print("=" * 50)
print("OmniSuite Engine Test")
print("=" * 50)

import torch
import soundfile as sf
import numpy as np

print(f"torch {torch.__version__}")
torch_runtime = get_torch_runtime_config()
print(describe_torch_runtime(torch_runtime))
print(f"torchcodec available: {is_torchcodec_available()}")

from omnivoice import OmniVoice

print("\nLoading model...")
t0 = time.time()
model = OmniVoice.from_pretrained(
    "k2-fsa/OmniVoice",
    device_map=torch_runtime.device_map,
    dtype=torch_runtime.dtype,
)
print(f"Model loaded ({time.time() - t0:.1f}s)")

# Check generate signature
import inspect

sig = inspect.signature(model.generate)
print(f"\nmodel.generate signature: {sig}")

# Create a ref audio with actual sound (sine wave, not silence)
print("\nCreating reference audio (440Hz sine wave, 3 seconds)...")
sr = 24000
duration = 3.0
t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
sine_wave = 0.5 * np.sin(2 * np.pi * 440 * t)

with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
    sf.write(tmp.name, sine_wave, sr, format="WAV", subtype="PCM_16")
    ref_path = tmp.name

print(f"Ref audio: {ref_path} ({os.path.getsize(ref_path)} bytes)")

# Test 1: Generate with ref audio + preprocess_prompt=False
print("\n--- Test: generate with ref_audio + preprocess_prompt=False ---")
t0 = time.time()
try:
    result = model.generate(
        text="Hello world.",
        ref_audio=ref_path,
        ref_text="This is reference text.",
        preprocess_prompt=False,
    )

    audio_tensor = result[0] if isinstance(result, (list, tuple)) else result
    print(f"  Result shape: {audio_tensor.shape}, dtype: {audio_tensor.dtype}")

    audio_np = audio_tensor.cpu().numpy()
    if audio_np.ndim == 2:
        audio_np = audio_np.T

    sf.write("test_output.wav", audio_np, 24000, format="WAV", subtype="PCM_16")
    size = os.path.getsize("test_output.wav")
    print(f"  SUCCESS ({time.time() - t0:.1f}s) — test_output.wav ({size:,} bytes)")
except Exception as e:
    print(f"  FAIL ({time.time() - t0:.1f}s): {e}")

os.unlink(ref_path)
print("\n" + "=" * 50)
