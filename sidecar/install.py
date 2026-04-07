#!/usr/bin/env python
"""Install all OmniSuite sidecar dependencies in the correct order.

Usage:
    python install.py          # Install everything (CUDA auto-detected)
    python install.py --cpu    # Force CPU-only PyTorch
    python install.py --dev    # Also install dev deps (pyinstaller)
"""
import subprocess
import sys
import argparse


def run(cmd: list[str], check: bool = True):
    print(f"\n>>> {' '.join(cmd)}")
    result = subprocess.run(cmd, check=check)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpu", action="store_true", help="CPU-only PyTorch")
    parser.add_argument("--dev", action="store_true", help="Include dev deps")
    args = parser.parse_args()

    pip = [sys.executable, "-m", "pip", "install"]

    # Step 1: PyTorch + torchaudio with CUDA index
    print("=" * 60)
    print("Step 1: Installing PyTorch 2.11.0")
    print("=" * 60)
    torch_pkgs = ["torch==2.11.0", "torchaudio==2.11.0"]
    if args.cpu:
        run(pip + torch_pkgs + ["--index-url", "https://download.pytorch.org/whl/cpu"])
    else:
        run(pip + torch_pkgs + ["--index-url", "https://download.pytorch.org/whl/cu128"])

    # Step 2: Regular requirements (no torch conflicts)
    print("\n" + "=" * 60)
    print("Step 2: Installing server + OmniVoice dependencies")
    print("=" * 60)
    run(pip + ["-r", "requirements.txt"])

    # Step 3: OmniVoice package (--no-deps to skip torch==2.8.* pin)
    print("\n" + "=" * 60)
    print("Step 3: Installing OmniVoice (--no-deps)")
    print("=" * 60)
    run(pip + ["omnivoice", "--no-deps"])

    # Step 4: Dev deps
    if args.dev:
        print("\n" + "=" * 60)
        print("Step 4: Installing dev dependencies")
        print("=" * 60)
        run(pip + ["pyinstaller==6.19.0"])

    # Verify
    print("\n" + "=" * 60)
    print("Verifying installation...")
    print("=" * 60)
    result = subprocess.run(
        [sys.executable, "-c", """
import torch, torchaudio, fastapi, uvicorn, huggingface_hub
from omnivoice import OmniVoice
print(f"  torch:           {torch.__version__}")
print(f"  torchaudio:      {torchaudio.__version__}")
print(f"  fastapi:         {fastapi.__version__}")
print(f"  uvicorn:         {uvicorn.__version__}")
print(f"  huggingface_hub: {huggingface_hub.__version__}")
print(f"  omnivoice:       OK")
print(f"  CUDA:            {torch.cuda.is_available()} ({torch.version.cuda if torch.cuda.is_available() else 'N/A'})")
if torch.cuda.is_available():
    print(f"  GPU:             {torch.cuda.get_device_name(0)}")
print()
print("All dependencies installed successfully!")
"""],
        check=False,
    )
    if result.returncode != 0:
        print("\nVerification failed — check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
