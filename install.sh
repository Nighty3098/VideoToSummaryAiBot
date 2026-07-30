#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[*] Creating virtual environment..."
python3 -m venv venv

echo "[*] Activating and installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "[*] Installing Playwright Chromium browser..."
playwright install chromium

# Check for libcublas.so.12 (required by faster-whisper)
CUBLAS_PATH=$(find / -name libcublas.so.12 -type f 2>/dev/null | head -1)
if [ -n "$CUBLAS_PATH" ]; then
    CUBLAS_DIR=$(dirname "$CUBLAS_PATH")
    echo "[*] Found libcublas.so.12 in: $CUBLAS_DIR"
else
    echo "[!] WARNING: libcublas.so.12 not found. faster-whisper will fall back to CPU."
    echo "    Install CUDA 12.x or set LD_LIBRARY_PATH manually."
fi

echo "[+] Done! Run the bot with:"
echo "    source venv/bin/activate && python bot.py"
