"""Мелкие общие утилиты."""
from __future__ import annotations

import sys
from typing import Any


def force_utf8() -> None:
    """Windows-консоль по умолчанию cp1251/cp866 — без этого эмодзи роняют print()."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure: Any = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
