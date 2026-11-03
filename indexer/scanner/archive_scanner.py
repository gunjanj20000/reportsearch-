"""Compressed folder and archive scanner for extracting and indexing documents from ZIP and TAR archives."""

from __future__ import annotations
import hashlib
import os
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set

from ..config import ARCHIVES_CACHE_DIR, SUPPORTED_EXTENSIONS, is_archive_file, logger


@dataclass
class ArchiveDocument:
    extracted_path: Path
    archive_path: Path
    member_name: str
    virtual_source_path: str
    size: int
    modified_time: float
    extension: str


def get_archive_cache_key(archive_path: Path) -> str:
    """Generate a stable, unique cache directory name based on archive path and stat."""
    stat = archive_path.stat()
    raw = f"{archive_path.resolve()}_{stat.st_size}_{stat.st_mtime}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    # Clean stem for human readability
    safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in archive_path.stem)
    return f"{safe_stem}_{h}"


def is_safe_path(base_dir: Path, target_path: Path) -> bool:
    """Validate that target_path does not escape base_dir (Zip Slip protection)."""
    try:
        base_resolved = base_dir.resolve()
        target_resolved = target_path.resolve()
        return os.path.commonpath([str(base_resolved), str(target_resolved)]) == str(base_resolved)
    except (ValueError, OSError):
        return False


class ArchiveScanner:
    """Extracts and tracks supported documents contained within compressed archives."""

    def __init__(self, supported_extensions: Optional[Set[str]] = None):
        self.supported_extensions = {ext.lower() for ext in (supported_extensions or SUPPORTED_EXTENSIONS)}

    def is_archive(self, path: Path | str) -> bool:
        """Check if file has a recognized archive extension and exists."""
        p = Path(path)
        return is_archive_file(p) and p.is_file()

    def inspect_and_extract(self, archive_path: Path) -> List[ArchiveDocument]:
        """
        Inspect archive and extract only supported documents into cache.
        Returns list of ArchiveDocument records.
        """
        archive_path = archive_path.resolve()
        if not archive_path.is_file():
            return []

        cache_folder_name = get_archive_cache_key(archive_path)
        dest_dir = ARCHIVES_CACHE_DIR / cache_folder_name
        dest_dir.mkdir(parents=True, exist_ok=True)

        stamp_file = dest_dir / ".extracted_stamp"
        archive_stat = archive_path.stat()

        # If already extracted and stamp matches, return cached documents
        if stamp_file.exists():
            try:
                cached_stamp = stamp_file.read_text("utf-8").strip()
                expected_stamp = f"{archive_stat.st_size}:{archive_stat.st_mtime}"
                if cached_stamp == expected_stamp:
                    return self._collect_extracted_docs(dest_dir, archive_path)
            except Exception:
                pass

        logger.info(f"Extracting supported documents from compressed folder: {archive_path.name}...")
        extracted_docs: List[ArchiveDocument] = []
        name_lower = archive_path.name.lower()

        # 1. ZIP Archive Handling
        if name_lower.endswith(".zip"):
            try:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue

                        member_p = Path(info.filename)
                        ext = member_p.suffix.lower()

                        # Skip non-supported or internal Mac metadata
                        if ext not in self.supported_extensions or "__MACOSX" in info.filename or member_p.name.startswith("._"):
                            continue

                        target_p = dest_dir / member_p
                        if not is_safe_path(dest_dir, target_p):
                            logger.warning(f"Unsafe path in zip ignored: {info.filename}")
                            continue

                        target_p.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, open(target_p, "wb") as dst:
                            dst.write(src.read())

                        # Timestamp
                        mtime = archive_stat.st_mtime
                        try:
                            import datetime
                            dt = datetime.datetime(*info.date_time)
                            mtime = dt.timestamp()
                        except Exception:
                            pass

                        vpath = f"{archive_path}#{info.filename}"
                        extracted_docs.append(ArchiveDocument(
                            extracted_path=target_p,
                            archive_path=archive_path,
                            member_name=info.filename,
                            virtual_source_path=vpath,
                            size=info.file_size,
                            modified_time=mtime,
                            extension=ext
                        ))
            except (zipfile.BadZipFile, OSError) as e:
                logger.warning(f"Error reading zip archive {archive_path}: {e}")
                return []

        # 2. TAR / TAR.GZ / TAR.BZ2 / TAR.XZ Handling
        elif any(name_lower.endswith(t) for t in [".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"]):
            try:
                mode = "r:*"
                with tarfile.open(archive_path, mode) as tf:
                    for member in tf.getmembers():
                        if not member.isfile():
                            continue

                        member_p = Path(member.name)
                        ext = member_p.suffix.lower()

                        if ext not in self.supported_extensions or "__MACOSX" in member.name or member_p.name.startswith("._"):
                            continue

                        target_p = dest_dir / member_p
                        if not is_safe_path(dest_dir, target_p):
                            logger.warning(f"Unsafe path in tar ignored: {member.name}")
                            continue

                        target_p.parent.mkdir(parents=True, exist_ok=True)
                        f_obj = tf.extractfile(member)
                        if f_obj:
                            with open(target_p, "wb") as dst:
                                dst.write(f_obj.read())

                        vpath = f"{archive_path}#{member.name}"
                        extracted_docs.append(ArchiveDocument(
                            extracted_path=target_p,
                            archive_path=archive_path,
                            member_name=member.name,
                            virtual_source_path=vpath,
                            size=member.size,
                            modified_time=float(member.mtime or archive_stat.st_mtime),
                            extension=ext
                        ))
            except (tarfile.TarError, OSError) as e:
                logger.warning(f"Error reading tar archive {archive_path}: {e}")
                return []

        # Write cache stamp
        try:
            stamp_file.write_text(f"{archive_stat.st_size}:{archive_stat.st_mtime}", "utf-8")
        except Exception:
            pass

        logger.info(f"Extracted {len(extracted_docs)} documents from compressed folder: {archive_path.name}")
        return extracted_docs

    def _collect_extracted_docs(self, dest_dir: Path, archive_path: Path) -> List[ArchiveDocument]:
        """Collect already cached extracted documents."""
        docs: List[ArchiveDocument] = []
        try:
            for root, _, files in os.walk(dest_dir):
                for f in files:
                    if f.startswith("."):
                        continue
                    p = Path(root) / f
                    ext = p.suffix.lower()
                    if ext in self.supported_extensions:
                        rel = str(p.relative_to(dest_dir))
                        stat = p.stat()
                        docs.append(ArchiveDocument(
                            extracted_path=p,
                            archive_path=archive_path,
                            member_name=rel,
                            virtual_source_path=f"{archive_path}#{rel}",
                            size=stat.st_size,
                            modified_time=stat.st_mtime,
                            extension=ext
                        ))
        except Exception as e:
            logger.warning(f"Error collecting cached archive docs: {e}")
        return docs
