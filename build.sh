#!/bin/bash
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
echo "=== FindWords Desktop App Build ==="
echo "Project root: $PROJECT_ROOT"

# Step 1: Build frontend
echo ""
echo "[1/4] Building frontend..."
cd "$PROJECT_ROOT/frontend"
npm install
npm run build
echo "Frontend build complete: frontend/dist/"

# Step 2: Build Python backend with PyInstaller
echo ""
echo "[2/4] Building backend with PyInstaller..."
cd "$PROJECT_ROOT/backend"

# Ensure virtual environment and dependencies
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt
pip install pyinstaller

pyinstaller findwords-server.spec --clean -y
echo "Backend build complete: backend/dist/findwords-server"
deactivate

# Step 3: Install Electron dependencies
echo ""
echo "[3/4] Installing Electron dependencies..."
cd "$PROJECT_ROOT"
npm install

# Step 4: Package with electron-builder
echo ""
echo "[4/4] Packaging Electron app..."
npm run dist

echo ""
echo "=== Build complete! ==="
echo "Output: $PROJECT_ROOT/release/"
