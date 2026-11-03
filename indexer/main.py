"""Main entrypoint for the Medical Literature Indexer application."""

from __future__ import annotations
import sys
from pathlib import Path

# Add project root to sys.path so running from any directory works
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def main() -> None:
    # Check if CLI mode requested or subcommand provided
    cli_commands = {"scan", "stats", "retry", "clear", "search", "suggest", "synonyms"}
    if "--cli" in sys.argv or (len(sys.argv) > 1 and sys.argv[1] in cli_commands):
        if "--cli" in sys.argv:
            sys.argv.remove("--cli")
        from indexer.cli import main as cli_main
        cli_main()
        return

    # Desktop GUI mode via PySide6
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
