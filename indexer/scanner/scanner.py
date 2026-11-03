"""Folder and archive scanner for recursively discovering, unpacking, and classifying supported documents."""

from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple, Iterator, Optional

from ..config import SUPPORTED_EXTENSIONS, logger, resolve_network_path, is_archive_file
from .archive_scanner import ArchiveScanner, ArchiveDocument


@dataclass
class ScannedFile:
    path: Path
    size: int
    modified_time: float
    extension: str
    change_type: str = "new"  # 'new', 'modified', 'unchanged', 'deleted'
    sha256: Optional[str] = None
    archive_path: Optional[Path] = None
    archive_member: Optional[str] = None
    virtual_source_path: Optional[str] = None


@dataclass
class ScanResult:
    folders: List[Path]
    to_index: List[ScannedFile] = field(default_factory=list)
    unchanged: List[ScannedFile] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    total_found: int = 0
    total_bytes: int = 0


class FileScanner:
    """Recursively scans directories and compressed archives, identifying changes against indexed state."""

    def __init__(self, supported_extensions: Set[str] = SUPPORTED_EXTENSIONS):
        self.supported_extensions = {ext.lower() for ext in supported_extensions}
        self.archive_scanner = ArchiveScanner(self.supported_extensions)

    def scan(
        self,
        folders: List[Path | str],
        existing_paths: Optional[Dict[str, Tuple[float, int, str]]] = None
    ) -> ScanResult:
        """
        Scan given folders and compressed archives recursively.
        existing_paths: map of str(path) -> (modified_time, file_size, sha256) from database.
        """
        if existing_paths is None:
            existing_paths = {}

        valid_targets: List[Path] = []
        for f in folders:
            resolved_p = Path(resolve_network_path(str(f)))
            if resolved_p.exists():
                if resolved_p.is_dir() or self.archive_scanner.is_archive(resolved_p):
                    valid_targets.append(resolved_p.resolve())
                else:
                    logger.warning(f"Target path not a directory or supported archive: {f}")
            else:
                logger.warning(f"Target path not found: {f}")

        result = ScanResult(folders=valid_targets)
        seen_paths: Set[str] = set()

        for target in valid_targets:
            # Case 1: Target is a compressed folder / archive directly (e.g. trials.zip)
            if self.archive_scanner.is_archive(target):
                logger.info(f"Scanning compressed archive target: {target}")
                self._scan_archive(target, existing_paths, seen_paths, result)
                continue

            # Case 2: Target is a standard directory
            logger.info(f"Scanning folder: {target}")
            try:
                for root, _, files in os.walk(target, followlinks=True):
                    for file in files:
                        p = Path(root) / file

                        # Check if file is a nested compressed folder (e.g. zip, tar.gz)
                        if self.archive_scanner.is_archive(p):
                            self._scan_archive(p.resolve(), existing_paths, seen_paths, result)
                            continue

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
                            extension=ext,
                            virtual_source_path=resolved_str
                        )

                        if resolved_str in existing_paths:
                            db_mtime, db_size, db_sha256 = existing_paths[resolved_str]
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
                logger.error(f"Error walking folder {target}: {e}")

        # Detect deleted files belonging to the scanned targets
        for db_path_str in existing_paths:
            db_p = Path(db_path_str.split("#")[0])
            is_under_target = any(
                str(db_p).startswith(str(t)) for t in valid_targets
            )
            if is_under_target and db_path_str not in seen_paths:
                result.deleted.append(db_path_str)

        logger.info(
            f"Scan completed: {result.total_found} found, "
            f"{len(result.to_index)} to index ({len([f for f in result.to_index if f.change_type == 'new'])} new, "
            f"{len([f for f in result.to_index if f.change_type == 'modified'])} modified), "
            f"{len(result.unchanged)} unchanged, {len(result.deleted)} deleted."
        )
        return result

    def _scan_archive(
        self,
        archive_path: Path,
        existing_paths: Dict[str, Tuple[float, int, str]],
        seen_paths: Set[str],
        result: ScanResult
    ) -> None:
        """Extract and process supported documents inside a compressed folder."""
        archive_docs = self.archive_scanner.inspect_and_extract(archive_path)

        for ad in archive_docs:
            vpath = ad.virtual_source_path
            seen_paths.add(vpath)
            result.total_found += 1
            result.total_bytes += ad.size

            scanned = ScannedFile(
                path=ad.extracted_path,
                size=ad.size,
                modified_time=ad.modified_time,
                extension=ad.extension,
                archive_path=ad.archive_path,
                archive_member=ad.member_name,
                virtual_source_path=vpath
            )

            if vpath in existing_paths:
                db_mtime, db_size, db_sha256 = existing_paths[vpath]
                if ad.size == db_size and abs(ad.modified_time - db_mtime) < 0.01:
                    scanned.change_type = "unchanged"
                    scanned.sha256 = db_sha256
                    result.unchanged.append(scanned)
                else:
                    scanned.change_type = "modified"
                    result.to_index.append(scanned)
            else:
                scanned.change_type = "new"
                result.to_index.append(scanned)
