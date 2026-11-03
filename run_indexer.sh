#!/usr/bin/env bash
# ============================================================
#      Medical Literature Search - Linux Launcher
# ============================================================

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

# Fix potential NumPy X86_V2 incompatibility on older CPUs / virtual machine processors
if python3 -c "import numpy" 2>&1 | grep -q "X86_V2"; then
    echo "[INFO] Detected NumPy X86_V2 incompatibility with CPU. Installing compatible numpy<2.4.0..."
    pip install "numpy<2.4.0" --quiet
fi

# 3. Handle help, explicit CLI flag, or CLI subcommands
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    echo "Usage: ./run_indexer.sh [OPTIONS | COMMAND]"
    echo ""
    echo "Options / Commands:"
    echo "  (no arguments)     Auto-detects environment: launches Desktop GUI or Web Dashboard"
    echo "  --web              Launch Web Dashboard at http://localhost:8080"
    echo "  stats              Display 8-metric dashboard statistics in terminal"
    echo "  scan <folders...>  Scan and index specified directories"
    echo "  search <query>     Execute full-text search with snippet highlights"
    echo "  export             Export portable database for Mobile PWA"
    echo "  synonyms           View or add cardiology synonyms"
    echo "  retry              Retry failed documents"
    echo "  clear              Reset database"
    echo "  --cli <args>       Pass any argument directly to CLI"
    echo ""
    exit 0
fi

CLI_CMDS="scan stats retry clear search suggest synonyms export"
for cmd in $CLI_CMDS; do
    if [ "$1" = "$cmd" ] || [ "$1" = "--cli" ]; then
        if [ "$1" = "--cli" ]; then shift; fi
        exec python -m indexer.cli "$@"
    fi
done

if [ "$1" = "--web" ] || [ "$1" = "web" ]; then
    if [ "$1" = "--web" ] || [ "$1" = "web" ]; then shift; fi
    exec python -m indexer.web "$@"
fi

# 4. Probe PySide6 CPU compatibility in an isolated Python process
CAN_RUN_QT=false
if [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then
    # Test if Qt6 can initialize without CPU abort (SSE4.2 / POPCNT check)
    if python3 -c "import subprocess, sys; sys.exit(0 if subprocess.run([sys.executable, '-c', 'import PySide6.QtWidgets'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0 else 1)" 2>/dev/null; then
        CAN_RUN_QT=true
    fi
fi

# 5. Launch GUI or Web Dashboard
if [ "$CAN_RUN_QT" = true ]; then
    echo "[INFO] Graphical display and compatible CPU detected. Launching Desktop GUI..."
    python -m indexer.main "$@"
else
    if [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then
        echo "[NOTICE] Desktop Qt GUI is not supported by this processor / VM profile."
        echo "         (Qt 6.8+ requires SSE4.2 and POPCNT CPU instructions)."
        echo "         If running in a VM, enable 'Host CPU Passthrough' to run Qt6."
    else
        echo "[NOTICE] No graphical display detected (DISPLAY is not set)."
    fi
    echo ""
    echo "[INFO] Starting the Web Dashboard instead..."
    echo "       Open http://localhost:8080 in your browser to access the GUI."
    echo "       (To run in terminal CLI mode instead: ./run_indexer.sh stats)"
    echo ""
    exec python -m indexer.web "$@"
fi
