"""Standalone test of the Krita MCP socket server logic (no Krita/PyQt5).

Run: python test_server_standalone.py
"""

import importlib.util
import json
import os
import socket
import sys
import threading
import time

# Load server.py directly (bypass the package __init__ which imports `krita`).
_HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "krita_mcp_server",
    os.path.join(_HERE, "krita_mcp", "server.py"),
)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def recv_all(s):
    data = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    return data


threading.Thread(target=server._serve, daemon=True).start()
time.sleep(0.3)

# First call: define a variable, return a result
s = socket.create_connection((server.HOST, server.PORT), timeout=10)
s.sendall(json.dumps({"code": "x = 6 * 7\n__result__ = x"}).encode("utf-8"))
s.shutdown(socket.SHUT_WR)
time.sleep(0.3)
server._poll()  # simulate the GUI-thread QTimer
print("resp1:", recv_all(s).decode("utf-8").strip())
s.close()

# Second call: namespace persists, capture print output
s2 = socket.create_connection((server.HOST, server.PORT), timeout=10)
s2.sendall(json.dumps({"code": "print('x =', x)"}).encode("utf-8"))
s2.shutdown(socket.SHUT_WR)
time.sleep(0.3)
server._poll()
print("resp2:", recv_all(s2).decode("utf-8").strip())
s2.close()

# Third call: an exception is captured, not raised
s3 = socket.create_connection((server.HOST, server.PORT), timeout=10)
s3.sendall(json.dumps({"code": "1/0"}).encode("utf-8"))
s3.shutdown(socket.SHUT_WR)
time.sleep(0.3)
server._poll()
r3 = recv_all(s3).decode("utf-8")
print("resp3 has traceback:", "ZeroDivisionError" in r3)
s3.close()

print("STANDALONE TEST DONE")
