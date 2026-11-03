"""Main entrypoint for the Medical Literature Indexer application."""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path

# Add project root to sys.path so running from any directory works
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def is_pyside6_supported() -> bool:
    """Safely test in an isolated subprocess whether PySide6/Qt can run on this CPU."""
    try:
        res = subprocess.run(
            [sys.executable, "-c", "import PySide6.QtWidgets"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5
        )
        return res.returncode == 0
    except Exception:
        return False


def main() -> None:
    # 1. Check for Web Dashboard mode
    if "--web" in sys.argv or (len(sys.argv) > 1 and sys.argv[1] == "web"):
        from indexer.web import run_web_server
        port = 8080
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                try:
                    port = int(sys.argv[i + 1])
                except ValueError:
                    pass
        run_web_server(port=port)
        return

    # 2. Check if CLI mode requested or subcommand provided
    cli_commands = {"scan", "stats", "retry", "clear", "search", "suggest", "synonyms", "export"}
    if "--cli" in sys.argv or (len(sys.argv) > 1 and sys.argv[1] in cli_commands):
        if "--cli" in sys.argv:
            sys.argv.remove("--cli")
        from indexer.cli import main as cli_main
        cli_main()
        return

    # 3. Check if PySide6 Desktop GUI is supported by host CPU
    if not is_pyside6_supported():
        print("\n" + "=" * 65)
        print("  [NOTICE] Desktop Qt GUI is not supported on this CPU / VM environment.")
        print("  Qt 6.8+ requires SSE4.2 and POPCNT CPU instructions.")
        print("  (In Virtual Machines, enable 'Host CPU Passthrough' to run Qt6).")
        print("=" * 65)
        print("  [INFO] Launching zero-dependency Web Dashboard instead...")
        print("  Opening Web Dashboard at: http://localhost:8080/")
        print("=" * 65 + "\n")
        from indexer.web import run_web_server
        run_web_server(port=8080)
        return

    # 4. Desktop GUI mode via PySide6
    from PySide6.QtWidgets import QApplication
    from indexer.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Medical Literature Indexer")
    app.setOrganizationName("CardioSearch")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
