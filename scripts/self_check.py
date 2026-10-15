"""Load packaged synthetic checks only when explicitly requested."""

import importlib
import sys
from pathlib import Path


def run_self_check(module: str, function: str = "self_test") -> None:
    root = str(Path(__file__).resolve().parents[1])
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    try:
        getattr(importlib.import_module("tests.self_checks." + module), function)()
    finally:
        if added:
            sys.path.remove(root)
