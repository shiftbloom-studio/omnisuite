#!/usr/bin/env python
"""Build script for OmniSuite sidecar packaging.

Bundles the FastAPI + OmniVoice sidecar into a standalone Windows executable
using PyInstaller (onedir mode).

Usage:
    python build.py          # standard build
    python build.py --clean  # remove previous artefacts without rebuilding
"""

import subprocess
import sys
import os
import shutil
from pathlib import Path


def ensure_pyinstaller() -> None:
    """Install PyInstaller if it is not already available."""
    try:
        import PyInstaller  # noqa: F401
        print(f"PyInstaller {PyInstaller.__version__} found.")
    except ImportError:
        print("PyInstaller not found — installing...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
        )
        print("PyInstaller installed.")


def clean(sidecar_dir: Path) -> None:
    """Remove previous build and dist directories."""
    for name in ("dist", "build"):
        d = sidecar_dir / name
        if d.exists():
            print(f"Removing {d} ...")
            shutil.rmtree(d)


def build(sidecar_dir: Path, spec_file: Path) -> int:
    """Run PyInstaller with the spec file. Returns the process exit code."""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(spec_file),
        "--noconfirm",
    ]
    print(f"\nRunning: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=str(sidecar_dir))
    return result.returncode


def report(dist_dir: Path) -> None:
    """Print build results and total output size."""
    output_dir = dist_dir / "omnisuite-sidecar"
    exe = output_dir / "omnisuite-sidecar.exe"

    if not exe.exists():
        print("\nBUILD FAILED — omnisuite-sidecar.exe not found.")
        sys.exit(1)

    total_bytes = sum(
        f.stat().st_size
        for f in output_dir.rglob("*")
        if f.is_file()
    )
    total_gb = total_bytes / (1024 ** 3)
    total_mb = total_bytes / (1024 ** 2)

    file_count = sum(1 for _ in output_dir.rglob("*") if _.is_file())

    print("\n" + "=" * 60)
    print("BUILD SUCCESS")
    print("=" * 60)
    print(f"Executable : {exe}")
    print(f"Files      : {file_count}")
    if total_gb >= 1.0:
        print(f"Total size : {total_gb:.2f} GB")
    else:
        print(f"Total size : {total_mb:.0f} MB")
    print("=" * 60)


def main() -> None:
    sidecar_dir = Path(__file__).resolve().parent
    spec_file = sidecar_dir / "omnisuite-sidecar.spec"
    dist_dir = sidecar_dir / "dist"

    # --clean flag: wipe artefacts and exit
    if "--clean" in sys.argv:
        clean(sidecar_dir)
        print("Clean complete.")
        return

    if not spec_file.exists():
        print(f"Spec file not found: {spec_file}")
        sys.exit(1)

    ensure_pyinstaller()
    clean(sidecar_dir)

    rc = build(sidecar_dir, spec_file)
    if rc != 0:
        print(f"\nBUILD FAILED (exit code {rc})")
        sys.exit(1)

    report(dist_dir)


if __name__ == "__main__":
    main()
