from __future__ import annotations
import sys
from pathlib import Path

# Ensure local workspace sources are imported instead of any
# globally installed version of StrateQueue that might exist in
# the active virtual-env.  This has to happen *before* test
# modules import StrateQueue.* symbols, therefore we place it in
# a top-level conftest executed during collection.
PROJECT_ROOT = Path(__file__).resolve().parent.parent  # repo root
SRC_PATH = PROJECT_ROOT / "src"
if SRC_PATH.exists() and str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH)) 