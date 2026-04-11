#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

pick_python() {
  for candidate in python3.13 python3.12 python3.11 python3; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi

    if "$candidate" -c 'import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)'; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="$(pick_python || true)"
fi

if [ -z "${PYTHON_BIN:-}" ]; then
  printf 'Python 3.11, 3.12, or 3.13 is required for OmniSuite.\n' >&2
  exit 1
fi

export PYTORCH_ENABLE_MPS_FALLBACK="${PYTORCH_ENABLE_MPS_FALLBACK:-1}"

printf '========================================\n'
printf '  OmniSuite - Voice Synthesis & Cloning\n'
printf '========================================\n\n'
printf 'Using Python: %s\n' "$PYTHON_BIN"
printf 'Starting server at http://localhost:8000\n'
printf 'Press Ctrl+C to stop.\n\n'

exec "$PYTHON_BIN" -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload
