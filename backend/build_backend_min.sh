#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
VENV_DIR="$BACKEND_DIR/.packenv"

echo "[1/5] Create isolated packaging venv..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip wheel setuptools

echo "[2/5] Install backend deps..."
pip install -r "$BACKEND_DIR/requirements.txt"
# Ensure headless opencv (no Qt) is used — prevents import deadlock in PyInstaller
pip uninstall -y opencv-python 2>/dev/null || true
pip install opencv-python-headless
pip install pyinstaller

echo "[3/5] Clean old build artifacts..."
rm -rf "$BACKEND_DIR/build" "$BACKEND_DIR/dist"

echo "[4/5] Build backend executable (optimized spec, one-dir)..."
cd "$BACKEND_DIR"
python -m PyInstaller findwords-server.spec --clean -y

echo "[5/5] Result size:"
du -sh "$BACKEND_DIR/dist/findwords-server"
ls -lh "$BACKEND_DIR/dist/findwords-server/findwords-server"

echo "Done."
