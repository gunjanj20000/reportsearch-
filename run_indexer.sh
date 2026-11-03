#!/usr/bin/env bash
# ============================================================
#      Medical Literature Search - Linux Launcher
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "     Medical Literature Search - Linux Indexer"
echo "============================================================"
echo ""

# 1. Check Python 3
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python 3 is not installed or not in PATH."
    echo "Please install Python 3.12+ (e.g., sudo apt install python3 python3-venv python3-pip)"
    exit 1
fi

# 2. Setup / Activate Virtual Environment
if [ ! -f "venv/bin/activate" ]; then
    echo "[INFO] Virtual environment not found. Creating 'venv'..."
    python3 -m venv venv || {
        echo "[ERROR] Failed to create virtual environment."
        echo "You may need to run: sudo apt install python3-venv"
        exit 1
    }
    source venv/bin/activate
    echo "[INFO] Installing dependencies from requirements.txt..."
    pip install --upgrade pip
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# 3. Check Display environment for GUI
if [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ]; then
    echo "[NOTICE] No graphical display detected (DISPLAY is not set)."
    echo "[NOTICE] If you are in a remote SSH session, run the CLI instead:"
    echo "         ./run_indexer.sh --cli --help"
    echo ""
    echo "Starting CLI mode directly..."
    python -m indexer.cli "$@"
else
    echo "[INFO] Graphical display detected. Launching Desktop GUI..."
    python -m indexer.main "$@"
fi
