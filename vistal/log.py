"""Logging setup: console (stderr) plus an optional per-game log file."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

LOG = logging.getLogger("vistal")
_file_handler: logging.Handler | None = None


def setup(verbose: bool = False) -> None:
    if LOG.handlers:
        LOG.setLevel(logging.DEBUG if verbose else LOG.level)
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("vistal: %(message)s"))
    LOG.addHandler(handler)
    level = logging.DEBUG if verbose or os.environ.get("VISTAL_DEBUG") else logging.INFO
    LOG.setLevel(level)


def attach_file(path: Path) -> Path:
    """Mirror log output to `path` (replacing any previous log file)."""
    global _file_handler
    path.parent.mkdir(parents=True, exist_ok=True)
    if _file_handler is not None:
        LOG.removeHandler(_file_handler)
        _file_handler.close()
    _file_handler = logging.FileHandler(path, mode="w", encoding="utf-8")
    _file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _file_handler.setLevel(logging.DEBUG)
    LOG.addHandler(_file_handler)
    if LOG.level > logging.DEBUG:
        # keep console quiet but capture debug detail in the file
        for h in LOG.handlers:
            if h is not _file_handler:
                h.setLevel(LOG.level)
        LOG.setLevel(logging.DEBUG)
    return path
