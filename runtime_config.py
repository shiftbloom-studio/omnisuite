"""Portable PyTorch runtime selection for OmniSuite."""

from __future__ import annotations

import os
import platform
from importlib.util import find_spec
from dataclasses import dataclass

if platform.system() == "Darwin":
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import torch


@dataclass(frozen=True)
class TorchRuntimeConfig:
    device_map: str
    dtype: torch.dtype
    acceleration: str


def get_torch_runtime_config() -> TorchRuntimeConfig:
    """Select the best portable runtime for the current machine."""
    if torch.backends.mps.is_available():
        return TorchRuntimeConfig(
            device_map="mps",
            dtype=torch.float32,
            acceleration="apple-metal",
        )

    return TorchRuntimeConfig(
        device_map="cpu",
        dtype=torch.float32,
        acceleration="cpu",
    )


def describe_torch_runtime(config: TorchRuntimeConfig | None = None) -> str:
    active_config = config or get_torch_runtime_config()
    dtype_name = str(active_config.dtype).replace("torch.", "")
    fallback_enabled = os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "1"
    fallback_suffix = ""

    if active_config.device_map == "mps" and fallback_enabled:
        fallback_suffix = ", cpu-fallback=on"

    return (
        f"device={active_config.device_map}, dtype={dtype_name}, "
        f"acceleration={active_config.acceleration}{fallback_suffix}"
    )


def is_torchcodec_available() -> bool:
    """Return whether TorchCodec is importable in the current environment."""
    return find_spec("torchcodec") is not None
