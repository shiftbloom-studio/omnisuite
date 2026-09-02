#!/usr/bin/env bash
# OmniSuite installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/shiftbloom-studio/omnisuite/main/install.sh | sh
#
# Installs OmniSuite into ~/.omnisuite and links `omnisuite` into ~/.local/bin.
# Requires Python 3.11–3.13 and a working internet connection.

set -euo pipefail

VERSION="0.1.0"                                          # bump on each release
REPO="https://github.com/shiftbloom-studio/omnisuite"

INSTALL_DIR="${OMNISUITE_HOME:-$HOME/.omnisuite}"
BIN_DIR="${OMNISUITE_BIN_DIR:-$HOME/.local/bin}"
APP_DIR="$INSTALL_DIR/$VERSION"
VENV_DIR="$INSTALL_DIR/venv"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

# ── 1. Locate Python 3.11–3.13 ─────────────────────────────────────────────
PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)'; then
    PYTHON_BIN="$candidate"
    break
  fi
done
[ -n "$PYTHON_BIN" ] || fail "Python 3.11–3.13 is required (e.g. brew install python@3.13)."
info "Using Python: $PYTHON_BIN"

# ── 2. Download the release bundle + its checksum ───────────────────────────
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
info "Downloading OmniSuite v$VERSION"
curl -fsSL "$REPO/releases/download/v$VERSION/omnisuite-v$VERSION.zip"    -o "$TMP/bundle.zip"
curl -fsSL "$REPO/releases/download/v$VERSION/omnisuite-v$VERSION.sha256" -o "$TMP/bundle.sha256"

# ── 3. Verify the sha256 checksum (sha256sum on Linux, shasum on macOS) ────
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}
[ "$(sha256_of "$TMP/bundle.zip")" = "$(awk '{print $1}' "$TMP/bundle.sha256")" ] \
  || fail "Checksum verification failed — aborting."

# ── 4. Extract into the install directory ──────────────────────────────────
mkdir -p "$APP_DIR"
"$PYTHON_BIN" -m zipfile -e "$TMP/bundle.zip" "$TMP/extracted"
cp -R "$TMP/extracted/omnisuite-v$VERSION/." "$APP_DIR/"

# ── 5. Create a virtualenv and install dependencies (~300 MB) ──────────────
info "Creating virtualenv and installing dependencies (this can take a few minutes)..."
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

# ── 6. Install the `omnisuite` launcher ────────────────────────────────────
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/omnisuite" <<EOF
#!/usr/bin/env bash
exec "$VENV_DIR/bin/python" -m uvicorn app:app --app-dir "$APP_DIR" --host 127.0.0.1 --port 8000 "\$@"
EOF
chmod +x "$BIN_DIR/omnisuite"

info "Installed OmniSuite v$VERSION to $APP_DIR"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) printf '\nAdd %s to your PATH:\n    export PATH="%s:$PATH"\n' "$BIN_DIR" "$BIN_DIR" ;;
esac

printf '\nRun it with:\n    omnisuite\n… then open http://localhost:8000\n'
