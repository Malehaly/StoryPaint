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

# Allowed message types on the wire (whitelist).
ALLOWED_MESSAGE_TYPES = (MSG_HELLO, MSG_EXPORT, MSG_IMPORT_BACK, MSG_STATUS)

# Defensive caps on collection sizes inside a message. The raw payload is
# already bounded by MAX_MESSAGE_BYTES; these only stop absurdly nested lists.
# Generous on purpose: messages carry file PATHS and frame metadata, never
# image pixels, so real artwork (however heavy) is never limited here.
MAX_LAYERS = 4096
MAX_FRAMES_PER_LAYER = 200000
MAX_PATH_LEN = 4096


def validate_message(msg):
    """Validate a decoded JSON message; return it or raise ``ValueError``.

    Data-only safety net on top of JSON: whitelist of message types, required
    fields per type, and type/size checks on the values. Both sides use this.
    """
    if not isinstance(msg, dict):
        raise ValueError("bridge message must be an object")
    mtype = msg.get("type")
    if not isinstance(mtype, str):
        raise ValueError("bridge message missing a string type")
    if mtype not in ALLOWED_MESSAGE_TYPES:
        raise ValueError("unknown bridge message type")

    if mtype == MSG_HELLO:
        app = msg.get("application")
        if app is not None and not isinstance(app, str):
            raise ValueError("HELLO.application must be a string")
        return msg

    if mtype == MSG_STATUS:
        for key in ("status", "text", "message"):
            value = msg.get(key)
            if value is not None and not isinstance(value, str):
                raise ValueError("STATUS field must be a string")
        return msg

    # EXPORT and IMPORT_BACK both carry a per-layer list.
    if not isinstance(msg.get("object_uuid"), str):
        raise ValueError(f"{mtype} missing object_uuid")
    layers = msg.get("layers")
    if not isinstance(layers, list) or len(layers) > MAX_LAYERS:
        raise ValueError(f"{mtype} layers must be a bounded list")
    for layer in layers:
        if not isinstance(layer, dict):
            raise ValueError(f"{mtype} layer must be an object")
        if not isinstance(layer.get("name"), str):
            raise ValueError(f"{mtype} layer missing a name")
        if mtype == MSG_EXPORT:
            files = layer.get("files")
            if not isinstance(files, list):
                raise ValueError("EXPORT layer.files must be a list")
            for path in files:
                if not isinstance(path, str) or len(path) > MAX_PATH_LEN:
                    raise ValueError("EXPORT layer.files item must be a bounded string")
            active = layer.get("active_frames")
            if active is not None and not isinstance(active, list):
                raise ValueError("EXPORT active_frames must be a list")
        else:  # IMPORT_BACK
            frames = layer.get("frames")
            if not isinstance(frames, list) or len(frames) > MAX_FRAMES_PER_LAYER:
                raise ValueError("IMPORT_BACK layer.frames must be a bounded list")
            for frame in frames:
                if not isinstance(frame, dict) or not isinstance(frame.get("file"), str):
                    raise ValueError("IMPORT_BACK frame must be an object with a file string")
    return msg
