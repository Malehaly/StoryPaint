"""Stable identifiers for exported content (headless; no bpy).

Identity is the backbone of the bridge: every Blender Grease Pencil object gets
a persistent `object_uuid` custom property, and every exported unit gets its own
id. Names are never used as identity (objects can be renamed or duplicated).
"""

from __future__ import annotations

import uuid


def new_uuid() -> str:
    """Return a new RFC 4122 UUID string (no braces, lowercase hex)."""
    return str(uuid.uuid4())


def is_uuid(value: str | None) -> bool:
    """Return True if *value* parses as a UUID string."""
    if not value:
        return False
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False
