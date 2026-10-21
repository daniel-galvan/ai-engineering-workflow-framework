"""Framework regression tests and packaged self-check scenarios."""

import os


# Synthetic tests must opt in to native-session fixtures instead of inheriting the host chat.
os.environ["CODEX_THREAD_ID"] = ""
os.environ["CODEX_SESSION_ID"] = ""
