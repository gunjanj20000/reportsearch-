"""Medical Literature Search - Indexer Package."""

import sys

# CPU Instruction Compatibility Guard:
# On CPUs or VMs without x86-64-v2 (SSE4.2 / POPCNT),
# pre-compiled wheels of NumPy 2.4+ raise RuntimeError on import.
# PyMuPDF and Pillow work completely fine without NumPy, but pytesseract
# only catches ModuleNotFoundError when importing numpy.
# By safely handling NumPy import failure here, we ensure the entire application
# (extractors, search engine, web dashboard, and CLI) runs seamlessly on any machine.
try:
    import numpy
except Exception:
    sys.modules["numpy"] = None

__version__ = "1.0.0"
