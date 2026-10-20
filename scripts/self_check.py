"""Load packaged synthetic checks only when explicitly requested."""

import importlib
import os
import sys
from pathlib import Path


def run_self_check(module: str, function: str = "self_test") -> None:
    root = str(Path(__file__).resolve().parents[1])
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    # Synthetic scenarios must never bind to the editing chat's native provider history.
    native = {key: os.environ.pop(key) for key in ("CODEX_THREAD_ID", "CODEX_SESSION_ID") if key in os.environ}
    try:
        getattr(importlib.import_module("tests.self_checks." + module), function)()
    finally:
        for key in ("CODEX_THREAD_ID", "CODEX_SESSION_ID"):
            os.environ.pop(key, None)
        os.environ.update(native)
        if added:
            sys.path.remove(root)
