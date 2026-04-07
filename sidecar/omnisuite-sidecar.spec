# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for OmniSuite sidecar (FastAPI + OmniVoice + PyTorch/CUDA)."""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
# Limit CUDA fat-binary architectures to keep the bundle size manageable.
os.environ["TORCH_CUDA_ARCH_LIST"] = "7.0;7.5;8.0;8.6;8.9;9.0"

SIDECAR_DIR = Path(SPECPATH)  # directory containing this .spec file
ENTRY_POINT = str(SIDECAR_DIR / "server.py")

# ---------------------------------------------------------------------------
# Data files
# ---------------------------------------------------------------------------
# Collect package data that PyInstaller cannot discover via import analysis.
datas = []
datas += collect_data_files("omnivoice", include_py_files=False)
datas += collect_data_files("huggingface_hub", include_py_files=False)

# ---------------------------------------------------------------------------
# Hidden imports
# ---------------------------------------------------------------------------
# PyInstaller misses many lazy / dynamic imports in these packages.
hiddenimports = [
    # --- uvicorn internals ---
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    # --- web framework ---
    "fastapi",
    "starlette",
    "starlette.responses",
    "starlette.routing",
    "starlette.middleware",
    "starlette.middleware.cors",
    "pydantic",
    "pydantic_core",
    "pydantic_core._pydantic_core",
    # --- PyTorch / audio ---
    "torch",
    "torch._C",
    "torch.utils",
    "torch.utils.data",
    "torchaudio",
    "torchaudio.transforms",
    "torchaudio.functional",
    # --- OmniVoice ---
    "omnivoice",
    # --- Hugging Face ---
    "huggingface_hub",
    "huggingface_hub.utils",
    # --- socket / engine (uvicorn websocket deps) ---
    "engineio",
    "socketio",
]

# Collect every sub-module of torch so nothing is missed at runtime.
hiddenimports += collect_submodules("torch")
hiddenimports += collect_submodules("torchaudio")

# ---------------------------------------------------------------------------
# Excludes — trim modules we will never need
# ---------------------------------------------------------------------------
excludes = [
    "tkinter",
    "_tkinter",
    "test",
    "unittest",
    "distutils",
    "setuptools",
    "pip",
    "torch.distributed",
    "torch.testing",
    "torch.utils.bottleneck",
    "torch.utils.tensorboard",
    "matplotlib",
    "IPython",
    "jupyter",
    "notebook",
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    [ENTRY_POINT],
    pathex=[str(SIDECAR_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# ---------------------------------------------------------------------------
# PYZ archive
# ---------------------------------------------------------------------------
pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# Executable
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # onedir mode — binaries live next to the exe
    name="omnisuite-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,            # background server — needs a console for logs
)

# ---------------------------------------------------------------------------
# Collect into a single directory (onedir)
# ---------------------------------------------------------------------------
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="omnisuite-sidecar",
)
