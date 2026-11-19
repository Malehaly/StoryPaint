"""Krita-side client to Blender's bridge server.

Mirror of `blender_krita_bridge/core/protocol.py` — keep constants in sync.
Messages are JSON dicts sent with send_bytes/recv_bytes (never pickle); the
auth key is a random per-install key stored in ``bridge_key.json`` next to this
module (Blender writes it when the bridge is enabled / the plugin is installed).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from multiprocessing.connection import Client

HOST = "127.0.0.1"
PORT = 65432
MAX_MESSAGE_BYTES = 64 * 1024 * 1024

MSG_HELLO = "HELLO"
MSG_EXPORT = "EXPORT"
MSG_IMPORT_BACK = "IMPORT_BACK"
MSG_STATUS = "STATUS"

# Allowed message types on the wire (whitelist).
_ALLOWED_MESSAGE_TYPES = (MSG_HELLO, MSG_EXPORT, MSG_IMPORT_BACK, MSG_STATUS)

# Defensive caps on collection sizes inside a message. The raw payload is
# already bounded by MAX_MESSAGE_BYTES; these only stop absurdly nested lists.
# Generous on purpose: messages carry file PATHS and frame metadata, never
# image pixels, so real artwork (however heavy) is never limited here.
MAX_LAYERS = 4096
MAX_FRAMES_PER_LAYER = 200000
MAX_PATH_LEN = 4096


def validate_message(msg):
    """Validate a decoded JSON message; return it or raise ``ValueError``.

    Mirror of ``blender_krita_bridge/core/protocol.py`` — keep in sync.
    """
    if not isinstance(msg, dict):
        raise ValueError("bridge message must be an object")
    mtype = msg.get("type")
    if not isinstance(mtype, str):
        raise ValueError("bridge message missing a string type")
    if mtype not in _ALLOWED_MESSAGE_TYPES:
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

_KEY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "bridge_key.json"
)


def _load_authkey():
    """Read the per-install key (written by Blender); None until it exists."""
    try:
        with open(_KEY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    key = data.get("key") if isinstance(data, dict) else None
    if isinstance(key, str) and key:
        return key.encode("ascii")
    return None


def _send_json(conn, msg):
    conn.send_bytes(json.dumps(msg).encode("utf-8"))


def _recv_json(conn):
    raw = conn.recv_bytes(MAX_MESSAGE_BYTES)
    msg = json.loads(raw.decode("utf-8"))
    return validate_message(msg)


def _log(event: str, detail: str = ""):
    """Append a line to the Krita bridge log (for debugging silent failures)."""
    try:
        d = os.path.join(tempfile.gettempdir(), "BlenderKritaBridge")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "krita_bridge.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {event}: {detail}\n")
    except OSError:
        pass


class BridgeClient:
    """Connects to Blender's listener and exchanges JSON dict messages.

    All socket I/O (send AND recv) happens on the single ``_run`` thread; a
    `multiprocessing.connection.Connection` must NOT be used from two threads
    at once (that caused segfaults when ``send()`` ran on the UI thread while
    ``_run`` was polling/recv-ing). ``send()`` from any thread just enqueues.
    """

    def __init__(self):
        self._conn = None
        self._running = False
        self._thread = None
        self._inbox = []
        self._outbox = []
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._conn is not None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while self._running:
            authkey = _load_authkey()
            if authkey is None:
                # Blender hasn't written the key yet (bridge not enabled, or
                # the plugin was installed manually before Blender ran).
                for _ in range(6):
                    if not self._running:
                        return
                    time.sleep(0.5)
                continue
            try:
                with Client((HOST, PORT), authkey=authkey) as conn:
                    with self._lock:
                        self._conn = conn
                    _log("CONNECT", "connected to Blender")
                    try:
                        _send_json(conn, {"type": MSG_HELLO, "application": "Krita"})
                    except (OSError, EOFError):
                        pass
                    while self._running:
                        # Send any queued outbound messages (this thread owns the socket).
                        with self._lock:
                            pending = self._outbox
                            self._outbox = []
                        send_failed = False
                        for msg in pending:
                            try:
                                _send_json(conn, msg)
                            except (OSError, EOFError):
                                # The peer closed the socket. Break out of the
                                # WHOLE inner loop to force a reconnect — do NOT
                                # keep polling a dead connection (that silently
                                # drops every later message while `send()` keeps
                                # reporting True, because `_conn` stays set).
                                send_failed = True
                                break
                        if send_failed:
                            break
                        # Receive any inbound message.
                        try:
                            if not conn.poll(0.05):
                                continue
                            msg = _recv_json(conn)
                            with self._lock:
                                self._inbox.append(msg)
                        except (OSError, EOFError, ValueError):
                            break
            except (OSError, EOFError, ConnectionRefusedError):
                pass
            finally:
                with self._lock:
                    self._conn = None
                _log("DISCONNECT", "connection closed")
            # Back off before the next reconnect attempt.
            for _ in range(6):
                if not self._running:
                    break
                time.sleep(0.5)

    def send(self, msg) -> bool:
        """Queue ``msg`` for the connection thread; return False if not connected."""
        with self._lock:
            if self._conn is None:
                return False
            self._outbox.append(msg)
            return True

    def drain_inbox(self) -> list:
        with self._lock:
            msgs = self._inbox
            self._inbox = []
        return msgs

    def stop(self):
        self._running = False
        with self._lock:
            self._conn = None
