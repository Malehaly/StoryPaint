"""Socket bridge between Blender and Krita (multiprocessing.connection).

Blender is the listener (server); Krita connects and stays connected. Messages
are pickled dicts. Received messages are queued and drained by a `bpy.app.timers`
callback so bpy work runs on the main thread (see `register_timer`).
"""

from __future__ import annotations

import threading
from multiprocessing.connection import Listener

import bpy

from ..core import protocol

_POLL_INTERVAL = 0.2


class BridgeServer:
    """Blender-side listener that exchanges messages with the Krita plugin.

    All socket I/O (send AND recv) happens on the single ``_serve`` thread; a
    `multiprocessing.connection.Connection` must NOT be used from two threads at
    once. ``send()`` from any thread just enqueues. The ``_serve`` thread also
    survives client crashes (they must not kill the accept loop).
    """

    _instance = None

    def __init__(self):
        self._listener = None
        self._conn = None
        self._thread = None
        self._running = False
        self._inbox = []
        self._outbox = []
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> "BridgeServer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def running(self) -> bool:
        return self._running

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._conn is not None

    def start(self):
        # Self-heal: recover from a dead serve thread (which leaves the listener
        # socket bound but nobody calling accept()).
        if self._running and self._thread is not None and self._thread.is_alive():
            return
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
            self._listener = None
        self._running = True
        try:
            self._listener = Listener(
                (protocol.BRIDGE_HOST, protocol.BRIDGE_PORT),
                authkey=protocol.BRIDGE_AUTHKEY,
            )
        except OSError:
            # Port already in use (another Blender instance) — nothing to serve.
            self._listener = None
            self._running = False
            return
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while self._running and self._listener is not None:
            try:
                conn = self._listener.accept()
            except OSError:
                break
            with self._lock:
                self._conn = conn
            _log("CONNECT", "client accepted")
            try:
                self._read_loop(conn)
            except Exception as exc:  # noqa: BLE001
                print("BRIDGE: client read loop ended:", type(exc).__name__, exc)
            finally:
                with self._lock:
                    self._conn = None
                # Explicitly close the dead connection. Without this the local
                # `conn` reference keeps the socket object alive while we block
                # in accept(), so the peer never sees a close and never
                # reconnects (half-open socket → "sent but never arrives").
                try:
                    conn.close()
                except OSError:
                    pass
                _log("DISCONNECT", "client closed")

    def _read_loop(self, conn):
        while self._running:
            # Send any queued outbound messages (this thread owns the socket).
            with self._lock:
                pending = self._outbox
                self._outbox = []
            for msg in pending:
                try:
                    conn.send(msg)
                except (OSError, EOFError):
                    return
            # Receive any inbound message.
            try:
                if not conn.poll(_POLL_INTERVAL):
                    continue
                msg = conn.recv()
            except (EOFError, OSError):
                return
            except Exception as exc:  # noqa: BLE001
                print("BRIDGE: read error:", type(exc).__name__, exc)
                return
            with self._lock:
                self._inbox.append(msg)

    def send(self, msg) -> bool:
        """Queue ``msg`` for the serve thread; return False if not connected."""
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
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
            self._listener = None
        with self._lock:
            self._conn = None


def _handle_message(msg):
    mtype = msg.get("type")
    if mtype == protocol.MSG_IMPORT_BACK:
        from . import import_back

        result = import_back.apply_import_back(msg)
        print("BRIDGE:", result)
        _log("IMPORT_BACK", f"{len(msg.get('layers', []))} layers -> {result}")


def _log(event, detail):
    """Append a line to the bridge log file (for debugging silent failures)."""
    import os
    import tempfile
    import time

    try:
        d = os.path.join(tempfile.gettempdir(), "BlenderKritaBridge")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "bridge.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {event}: {detail}\n")
    except OSError:
        pass


def _poll_timer():
    # Fully exception-proof: if anything here raises, Blender silently
    # UNREGISTERS the timer, and then inbound messages pile up in the inbox
    # forever ("sent from Krita but never arrives in Blender").
    try:
        server = BridgeServer.instance()
        # Self-heal: if the serve thread died (or was never started), bring the
        # listener back without needing a file load. `start()` is a cheap no-op
        # when the server is already healthy.
        if not server.running or server._thread is None or not server._thread.is_alive():
            server.start()
        for msg in server.drain_inbox():
            try:
                _handle_message(msg)
            except Exception as exc:  # noqa: BLE001
                print("BRIDGE: error handling message:", type(exc).__name__, exc)
                _log("ERROR", f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001
        print("BRIDGE: poll error:", type(exc).__name__, exc)
        _log("POLL_ERROR", f"{type(exc).__name__}: {exc}")
    return _POLL_INTERVAL


def register_timer():
    # Self-heal: (re)register the drain timer if it is missing. Idempotent.
    if not bpy.app.timers.is_registered(_poll_timer):
        bpy.app.timers.register(_poll_timer, first_interval=_POLL_INTERVAL)


def unregister_timer():
    if bpy.app.timers.is_registered(_poll_timer):
        bpy.app.timers.unregister(_poll_timer)


@bpy.app.handlers.persistent
def _on_load_post(*_args):
    """Re-start the server + timer after a .blend load/new file.

    Loading a new file resets Blender's timer table, which silently kills the
    poll timer (symptom: "sent from Krita but never arrives"). The addon's
    ``register()`` does NOT re-run on file load, so we must re-register here.

    The ``@persistent`` decorator is REQUIRED: without it, File > New (and some
    file loads) remove this handler from ``bpy.app.handlers.load_post``, so the
    timer is never re-registered and inbound Krita messages never get drained.
    """
    try:
        BridgeServer.instance().start()
        register_timer()
        _log("LOAD_POST", "server + timer re-registered")
    except Exception as exc:  # noqa: BLE001
        print("BRIDGE: load_post error:", type(exc).__name__, exc)


def register_handler():
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister_handler():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
