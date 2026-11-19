"""Interchange protocol constants (headless; no bpy).

Single source of truth for the bridge's wire + on-disk package contract.
"""

from __future__ import annotations

# Bump on any breaking change to the on-disk format.
SCHEMA_VERSION = "0.1"

BRIDGE_NAME = "BlenderKritaBridge"

# Export formats. SVG is the vector candidate; PNG is the raster fallback that
# preserves appearance but not editable strokes.
FORMAT_SVG = "svg"
FORMAT_PNG = "png"
SUPPORTED_FORMATS = (FORMAT_SVG, FORMAT_PNG)

# Coordinate modes. The MVP targets 2D/projected content only; arbitrary 3D GP
# is explicitly out of scope until a well-defined SVG<->Blender transform exists.
COORDINATE_2D = "2d_projected"

# Socket bridge (Blender <-> Krita) over multiprocessing.connection.
# Messages are JSON dicts sent with send_bytes/recv_bytes (never pickle); the
# connection is authenticated by a per-install random key (see core/bridge_key).
# Keep in sync with krita_plugin/krita_bridge/connection.py.
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 65432

# Hard upper bound for a single message (defends against a misbehaving peer).
MAX_MESSAGE_BYTES = 64 * 1024 * 1024  # 64 MiB

MSG_HELLO = "HELLO"              # peer announces itself on connect
MSG_EXPORT = "EXPORT"            # Blender -> Krita: show the drawing
MSG_IMPORT_BACK = "IMPORT_BACK"  # Krita -> Blender: return the edited drawing
MSG_STATUS = "STATUS"            # either direction: human-readable status
