"""Automated tests for FileScanner and incremental detection."""

import time
import tempfile
from pathlib import Path

from indexer.scanner.scanner import FileScanner
from indexer.extractors.base import calculate_sha256


def test_file_scanner_discovers_all_types():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "sub1").mkdir()
        (root / "sub2").mkdir()

        (root / "sub1" / "doc1.pdf").write_text("dummy pdf")
        (root / "sub1" / "doc2.docx").write_text("dummy docx")
        (root / "sub2" / "doc3.doc").write_text("dummy doc")
        (root / "sub2" / "doc4.txt").write_text("dummy txt")
        (root / "sub2" / "ignored.exe").write_text("executable")
        (root / "sub2" / "ignored.jpg").write_text("image")

        scanner = FileScanner()
        res = scanner.scan([root])

        assert res.total_found == 4
        assert len(res.to_index) == 4
        assert all(f.change_type == "new" for f in res.to_index)


def test_incremental_change_detection():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        file1 = root / "cardio1.pdf"
        file1.write_text("content 1")
        stat1 = file1.stat()

        file2 = root / "cardio2.txt"
        file2.write_text("content 2")
        stat2 = file2.stat()

        existing_paths = {
            str(file1.resolve()): (stat1.st_mtime, stat1.st_size, "hash1"),
            str(file2.resolve()): (stat2.st_mtime, stat2.st_size, "hash2"),
        }

        scanner = FileScanner()

        # 1. Unchanged scan
        res1 = scanner.scan([root], existing_paths)
        assert len(res1.unchanged) == 2
        assert len(res1.to_index) == 0
        assert len(res1.deleted) == 0

        # 2. Modify file2
        time.sleep(0.05)
        file2.write_text("modified content 2 with more words")
        res2 = scanner.scan([root], existing_paths)
        assert len(res2.unchanged) == 1
        assert len(res2.to_index) == 1
        assert res2.to_index[0].path == file2.resolve()
        assert res2.to_index[0].change_type == "modified"

        # 3. Add file3
        file3 = root / "cardio3.docx"
        file3.write_text("new docx")
        res3 = scanner.scan([root], existing_paths)
        assert any(f.path == file3.resolve() and f.change_type == "new" for f in res3.to_index)

        # 4. Delete file1
        file1.unlink()
        res4 = scanner.scan([root], existing_paths)
        assert str(file1.resolve()) in res4.deleted


def test_sha256_streaming():
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = Path(tmp_dir) / "hash_test.txt"
        test_file.write_text("Medical Literature Search Engine SHA-256")
        h = calculate_sha256(test_file)
        assert len(h) == 64
        assert isinstance(h, str)
