#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN=${PYTHON_BIN:-python3}
VENV_DIR=${VENV_DIR:-.venv}

echo "[hi-clip] Using python executable: ${PYTHON_BIN}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python was not found. Please install Python 3.10+ and re-run." >&2
  exit 1
fi

if ! command -v tesseract >/dev/null 2>&1; then
  echo "[hi-clip] Tesseract is not installed or not on PATH." >&2
  echo "          Install it via your package manager (e.g., 'sudo apt install tesseract-ocr', 'brew install tesseract', or the Windows installer)." >&2
fi

echo "[hi-clip] Creating virtual environment at ${VENV_DIR}"
"$PYTHON_BIN" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "[hi-clip] Upgrading pip"
pip install --upgrade pip

echo "[hi-clip] Installing dependencies"
pip install -r requirements.txt

if [ ! -f config.yaml ]; then
  echo "[hi-clip] Creating config.yaml from sample"
  cp config.sample.yaml config.yaml
else
  echo "[hi-clip] config.yaml already exists; leaving in place"
fi

echo "[hi-clip] Installation complete. Activate with 'source ${VENV_DIR}/bin/activate' and run 'python -m halo_clip_creator'."
