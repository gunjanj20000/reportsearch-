"""Configuration and environment detection for Medical Literature Indexer."""

from __future__ import annotations
import os
import sys
import shutil
import logging
from pathlib import Path

# Supported document extensions
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}

# Supported compressed folder / archive extensions
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz"}

# Default application paths
APP_DIR = Path(os.environ.get("MEDSEARCH_HOME", Path(__file__).resolve().parent.parent))
DATA_DIR = APP_DIR / "data"
LOGS_DIR = APP_DIR / "logs"
EXPORTS_DIR = DATA_DIR / "exports"
ARCHIVES_CACHE_DIR = DATA_DIR / "archive_cache"
DEFAULT_DB_PATH = DATA_DIR / "medical_search.db"

# Ensure data, log, and archive directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVES_CACHE_DIR.mkdir(parents=True, exist_ok=True)

def is_archive_file(path_or_name: Path | str) -> bool:
    """Check if file path or name has a recognized compressed folder / archive extension."""
    s = str(path_or_name).lower()
    return any(s.endswith(ext) for ext in [
        ".zip", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".tar"
    ])

# OCR Configuration
DEFAULT_OCR_LANGUAGES = "eng+hin"
MIN_TEXT_CHARS_FOR_NATIVE_PDF = 50  # Below this threshold on a page with images, OCR is triggered

def find_libreoffice_binary() -> str | None:
    """Detect LibreOffice / soffice binary across Windows, Linux, and macOS."""
    # Check environment variable first
    env_path = os.environ.get("LIBREOFFICE_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    # Check PATH
    for name in ["libreoffice", "soffice"]:
        found = shutil.which(name)
        if found:
            return found

    # Windows standard installation locations
    if sys.platform == "win32":
        standard_win_paths = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\LibreOffice\program\soffice.exe"),
        ]
        for win_path in standard_win_paths:
            if os.path.isfile(win_path):
                return win_path

    # Linux / macOS standard paths
    unix_paths = [
        "/usr/bin/libreoffice",
        "/usr/bin/soffice",
        "/usr/local/bin/libreoffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    for unix_path in unix_paths:
        if os.path.isfile(unix_path):
            return unix_path

    return None


def find_tesseract_binary() -> str | None:
    """Detect Tesseract OCR binary across Windows, Linux, and macOS."""
    # Check environment variable first
    env_path = os.environ.get("TESSERACT_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    # Check PATH
    found = shutil.which("tesseract")
    if found:
        return found

    # Windows standard installation locations
    if sys.platform == "win32":
        win_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for win_path in win_paths:
            if os.path.isfile(win_path):
                return win_path

    # Linux / macOS standard paths
    unix_paths = [
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/opt/homebrew/bin/tesseract",
    ]
    for unix_path in unix_paths:
        if os.path.isfile(unix_path):
            return unix_path

    return None


def setup_logger(name: str = "indexer", log_file: Path | None = None) -> logging.Logger:
    """Configure and return a structured logger with both file and console handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if already configured
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler
    if log_file is None:
        log_file = LOGS_DIR / "indexer.log"

    try:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Failed to attach file handler to {log_file}: {e}")

    return logger

def format_bytes(num_bytes: int) -> str:
    """Format bytes into readable units."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


# Global default logger
logger = setup_logger("medsearch")


def resolve_network_path(path_str: str) -> str:
    r"""
    Resolve and normalize network folder paths (Windows UNC, Linux CIFS/NFS/GVFS).
    Supports:
      - Windows UNC paths (\\server\share\subfolder)
      - Forward-slash network paths (//server/share/subfolder)
      - Linux SMB/CIFS URLs (smb://server/share/subfolder)
      - GNOME/Ubuntu GVFS automatic mount mapping (/run/user/<uid>/gvfs/smb-share:...)
      - Standard local and mounted directory paths (/mnt/..., /media/...)
    """
    if not path_str:
        return path_str

    clean = str(path_str).strip()

    # 1. Check if already directly accessible
    p = Path(clean)
    try:
        if p.exists() and p.is_dir():
            return str(p.resolve())
    except (PermissionError, OSError):
        pass

    # 2. Linux GVFS SMB resolution
    if sys.platform.startswith("linux"):
        import re
        m = re.match(r"^(?:\\\\|//|smb://)([^/\\\\]+)[/\\\\]([^/\\\\]+)(?:[/\\\\](.*))?$", clean)
        if m:
            server, share, subpath = m.group(1), m.group(2), m.group(3) or ""
            user_id = os.getuid() if hasattr(os, "getuid") else 1000
            gvfs_dir = Path(f"/run/user/{user_id}/gvfs")
            if gvfs_dir.exists():
                try:
                    for entry in gvfs_dir.iterdir():
                        name_lower = entry.name.lower()
                        if server.lower() in name_lower and share.lower() in name_lower:
                            target = entry / subpath if subpath else entry
                            if target.exists() and target.is_dir():
                                return str(target.resolve())
                except Exception:
                    pass

    return clean
