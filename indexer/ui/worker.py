"""PySide6 QThread worker for responsive background indexing without UI freezing."""

from __future__ import annotations
from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal

from ..engine.indexer_engine import IndexerEngine
from ..models import DashboardStats, ExtractedDocument


class IndexerWorker(QThread):
    """Background worker executing scan and indexing pipeline."""

    progress_signal = Signal(int, int, str, str)  # current, total, filename, msg
    stats_signal = Signal(object)                 # DashboardStats
    file_indexed_signal = Signal(object)          # ExtractedDocument
    status_signal = Signal(str)                   # status name
    error_signal = Signal(str, str)               # path, error msg
    finished_signal = Signal(object)              # ScanResult

    def __init__(self, engine: IndexerEngine, folders: List[Path | str], retry_mode: bool = False):
        super().__init__()
        self.engine = engine
        self.folders = folders
        self.retry_mode = retry_mode

        # Connect engine callbacks to emit Qt signals
        self.engine.on_progress = lambda c, t, f, m: self.progress_signal.emit(c, t, f, m)
        self.engine.on_stats_updated = lambda s: self.stats_signal.emit(s)
        self.engine.on_file_indexed = lambda d: self.file_indexed_signal.emit(d)
        self.engine.on_status_changed = lambda st: self.status_signal.emit(st)
        self.engine.on_error = lambda p, err: self.error_signal.emit(p, err)

    def run(self) -> None:
        try:
            if self.retry_mode:
                succeeded = self.engine.retry_failed_documents()
                self.finished_signal.emit(succeeded)
            else:
                result = self.engine.index_folders(self.folders)
                self.finished_signal.emit(result)
        except Exception as e:
            self.error_signal.emit("Engine Error", str(e))
            self.status_signal.emit("error")
