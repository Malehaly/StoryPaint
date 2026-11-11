"""Krita MCP — socket server for driving Krita from outside (VS Code).

Runs a TCP server inside Krita that accepts Python code and executes it in
Krita's embedded interpreter on the GUI thread, returning stdout + a `__result__`
value. The VS Code side connects via `krita_mcp_client.py`.
"""

from __future__ import annotations

import io
import json
import socket
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout

HOST = "127.0.0.1"
PORT = 9877

_namespace: dict = {}
_queue: list = []
_lock = threading.Lock()
_timer = None


def _exec_code(code: str) -> dict:
    out = io.StringIO()
    result = None
    try:
        with redirect_stdout(out), redirect_stderr(out):
            exec(compile(code, "<krita_mcp>", "exec"), _namespace)
        result = _namespace.get("__result__")
    except Exception as exc:  # noqa: BLE001
        out.write(traceback.format_exc())
        result = f"<exception: {type(exc).__name__}: {exc}>"
    return {
        "output": out.getvalue(),
        "result": repr(result) if result is not None else None,
    }


def _serve():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((HOST, PORT))
    except OSError as exc:
        print("krita_mcp: bind failed:", exc)
        return
    srv.listen(4)
    srv.settimeout(0.5)
    while True:
        try:
            conn, _addr = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(target=_handle_conn, args=(conn,), daemon=True).start()


def _handle_conn(conn):
    try:
        conn.settimeout(10.0)
        data = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        code = json.loads(data.decode("utf-8")).get("code", "")
        with _lock:
            _queue.append((conn, code))
    except Exception as exc:  # noqa: BLE001
        try:
            conn.sendall(
                json.dumps(
                    {"output": "", "result": f"<client error: {exc}>"}
                ).encode("utf-8")
            )
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _poll():
    """Drain the queue and execute on the GUI thread (QTimer callback)."""
    global _queue
    with _lock:
        items = _queue
        _queue = []
    for conn, code in items:
        resp = _exec_code(code)
        try:
            conn.sendall(json.dumps(resp).encode("utf-8"))
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def start():
    """Start the socket server thread + the GUI-thread poller."""
    global _timer
    from PyQt5.QtCore import QTimer

    threading.Thread(target=_serve, daemon=True).start()
    if _timer is None:
        _timer = QTimer()
        _timer.timeout.connect(_poll)
        _timer.start(200)
