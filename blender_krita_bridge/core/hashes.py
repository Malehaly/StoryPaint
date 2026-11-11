"""File hashing helpers (headless; no bpy).

Used to detect whether a returned file differs from the exported one
("no changes" state) and to validate the package before import.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 1024 * 1024


def sha256_file(path: str | Path) -> str:
    """Return the lowercase hex SHA-256 of a file's contents."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
