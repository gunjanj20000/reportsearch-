"""Folder scanner for recursively discovering and classifying supported documents."""

from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple, Iterator, Optional

from ..config import SUPPORTED_EXTENSIONS, logger


@dataclass
class ScannedFile:
    path: Path
    size: int
    modified_time: float
    extension: str
    change_type: str = "new"  # 'new', 'modified', 'unchanged', 'deleted'
    sha256: Optional[str] = None


@dataclass
class ScanResult:
    folders: List[Path]
    to_index: List[ScannedFile] = field(default_factory=list)
    unchanged: List[ScannedFile] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    total_found: int = 0
    total_bytes: int = 0


class FileScanner:
    """Recursively scans directories and identifies changes against indexed state."""

    def __init__(self, supported_extensions: Set[str] = SUPPORTED_EXTENSIONS):
        self.supported_extensions = {ext.lower() for ext in supported_extensions}

    def scan(
        self,
        folders: List[Path | str],
        existing_paths: Optional[Dict[str, Tuple[float, int, str]]] = None
    ) -> ScanResult:
        """
        Scan given folders recursively.
        existing_paths: map of str(path) -> (modified_time, file_size, sha256) from database.
        """
        if existing_paths is None:
            existing_paths = {}

        valid_folders = [Path(f).resolve() for f in folders if Path(f).exists() and Path(f).is_dir()]
        result = ScanResult(folders=valid_folders)
        seen_paths: Set[str] = set()

        for folder in valid_folders:
            logger.info(f"Scanning folder: {folder}")
            try:
                for root, _, files in os.walk(folder, followlinks=True):
                    for file in files:
                        p = Path(root) / file
                        ext = p.suffix.lower()
                        if ext not in self.supported_extensions:
                            continue

                        try:
                            stat = p.stat()
                        except (PermissionError, FileNotFoundError, OSError) as e:
                            logger.warning(f"Cannot stat {p}: {e}")
                            continue

                        resolved_str = str(p.resolve())
                        seen_paths.add(resolved_str)
                        result.total_found += 1
                        result.total_bytes += stat.st_size

                        scanned = ScannedFile(
                            path=p.resolve(),
                            size=stat.st_size,
                            modified_time=stat.st_mtime,
                            extension=ext
                        )

                        if resolved_str in existing_paths:
                            db_mtime, db_size, db_sha256 = existing_paths[resolved_str]
                            # Compare file size and mtime (allowing small float epsilon)
                            if stat.st_size == db_size and abs(stat.st_mtime - db_mtime) < 0.01:
                                scanned.change_type = "unchanged"
                                scanned.sha256 = db_sha256
                                result.unchanged.append(scanned)
                            else:
                                scanned.change_type = "modified"
                                result.to_index.append(scanned)
                        else:
                            scanned.change_type = "new"
                            result.to_index.append(scanned)

            except Exception as e:
                logger.error(f"Error walking folder {folder}: {e}")

        # Detect deleted files belonging to the scanned folders
        for db_path_str in existing_paths:
            db_p = Path(db_path_str)
            # Check if this database entry belongs to any of the currently scanned folders
            is_under_folder = any(
                str(db_p).startswith(str(f)) for f in valid_folders
            )
            if is_under_folder and db_path_str not in seen_paths:
                result.deleted.append(db_path_str)

        logger.info(
            f"Scan completed: {result.total_found} found, "
            f"{len(result.to_index)} to index ({len([f for f in result.to_index if f.change_type == 'new'])} new, "
            f"{len([f for f in result.to_index if f.change_type == 'modified'])} modified), "
            f"{len(result.unchanged)} unchanged, {len(result.deleted)} deleted."
        )
        return result
