class Omnisuite < Formula
  desc "Local voice synthesis and cloning server"
  homepage "https://github.com/shiftbloom-studio/omnisuite"
  url "https://github.com/shiftbloom-studio/omnisuite/releases/download/v0.1.0/omnisuite-v0.1.0.zip"
  sha256 "2ecacbd5d25e6841d26935965f9bf14ea03a61bee8eab48c7a1ccbbb3efb5eac"
  license "AGPL-3.0"

  depends_on "python@3.13"

  def install
    libexec.install Dir["*"]

    python = formula_opt_bin("python@3.13")/"python3.13"

    (bin/"omnisuite").write <<~EOS
      #!/bin/bash
      set -euo pipefail

      APP="#{libexec}"
      VENV="#{var}/omnisuite/venv"

      if [ ! -x "$VENV/bin/python" ]; then
        echo "OmniSuite: first run, installing Python dependencies (downloads ~300 MB)..." >&2
        mkdir -p "$(dirname "$VENV")"
        "#{python}" -m venv "$VENV"
        "$VENV/bin/pip" install --upgrade pip
        "$VENV/bin/pip" install -r "$APP/requirements.txt"
      fi

      export PYTORCH_ENABLE_MPS_FALLBACK="${PYTORCH_ENABLE_MPS_FALLBACK:-1}"
      exec "$VENV/bin/python" -m uvicorn app:app --app-dir "$APP" --host 127.0.0.1 --port 8000 "$@"
    EOS
  end

  test do
    assert_path_exists libexec/"app.py"
    assert_path_exists libexec/"requirements.txt"
    assert_path_exists libexec/"static/index.html"
  end
end
