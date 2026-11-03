"""Data structures for incremental synchronization update packages."""

from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional


@dataclass
class IncrementalUpdatePackage:
    """Portable delta payload representing document changes since a baseline timestamp."""

    created_at: str
    since_date: str
    schema_version: int = 1
    total_documents: int = 0
    total_paragraphs: int = 0
    documents: List[Dict[str, Any]] = field(default_factory=list)
    pages: List[Dict[str, Any]] = field(default_factory=list)
    paragraphs: List[Dict[str, Any]] = field(default_factory=list)
    deleted_source_paths: List[str] = field(default_factory=list)
    synonyms: List[Dict[str, Any]] = field(default_factory=list)

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> IncrementalUpdatePackage:
        data = json.loads(json_str)
        return cls(**data)
