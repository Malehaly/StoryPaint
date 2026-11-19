"""Per-install bridge auth key (headless; no bpy).

The bridge authenticates over ``multiprocessing.connection`` with an HMAC key.
Instead of a hard-coded key (which any local program could reuse), each
installation generates a random key and stores it inside the installed Krita
plugin directory — the one place Blender (which installs the plugin) and Krita
(which loads it) already agree on.
"""

from __future__ import annotations

import json
import os
import secrets

KEY_FILENAME = "bridge_key.json"


def new_key() -> str:
    """Return a fresh random key as a hex string (64 hex chars / 32 bytes)."""
    return secrets.token_hex(32)


def key_file_path() -> str:
    """Path of the shared key file (inside the installed Krita plugin dir)."""
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            return os.path.join(base, "krita", "pykrita", "krita_bridge", KEY_FILENAME)
        return os.path.join(
            os.path.expanduser("~"), ".krita", "pykrita", "krita_bridge", KEY_FILENAME
        )
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    candidates = [
        os.path.join(xdg, "krita", "pykrita", "krita_bridge", KEY_FILENAME),
        os.path.expanduser(
            "~/Library/Application Support/krita/pykrita/krita_bridge/" + KEY_FILENAME
        ),
    ]
    for c in candidates:
        if os.path.isdir(os.path.dirname(c)):
            return c
    return candidates[0]


def load_key(path: str | None = None) -> bytes | None:
    """Read the key from ``path`` (default shared location); ``None`` if absent."""
    p = path or key_file_path()
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    key = data.get("key") if isinstance(data, dict) else None
    if isinstance(key, str) and key:
        return key.encode("ascii")
    return None


def ensure_key(path: str | None = None) -> bytes:
    """Load the key, creating a fresh random one at ``path`` when missing."""
    p = path or key_file_path()
    key = load_key(p)
    if key is not None:
        return key
    key = new_key().encode("ascii")
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"key": key.decode("ascii")}, f)
    except OSError:
        pass  # read-only install: fall back to the in-memory key this session
    return key
