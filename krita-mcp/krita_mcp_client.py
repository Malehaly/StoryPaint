"""CLI client for the Krita MCP socket server.

Usage (from this folder, with any Python 3):
  python krita_mcp_client.py -c "print(1+1)"
  python krita_mcp_client.py -f script.py
  echo "code" | python krita_mcp_client.py
"""

from __future__ import annotations

import argparse
import json
import socket
import sys

HOST = "127.0.0.1"
PORT = 9877


def run(code: str) -> dict:
    s = socket.create_connection((HOST, PORT), timeout=30)
    s.sendall(json.dumps({"code": code}).encode("utf-8"))
    s.shutdown(socket.SHUT_WR)
    data = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data.decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Run Python code in a running Krita")
    parser.add_argument("-c", "--code", help="code string to execute")
    parser.add_argument("-f", "--file", help="path to a .py file to execute")
    args = parser.parse_args()

    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            code = fh.read()
    elif args.code:
        code = args.code
    else:
        code = sys.stdin.read()

    try:
        resp = run(code)
    except (ConnectionRefusedError, OSError) as exc:
        print(f"Could not connect to Krita ({HOST}:{PORT}). Is Krita running with the Krita MCP plugin enabled?")
        print(f"  ({type(exc).__name__}: {exc})")
        sys.exit(1)

    if resp.get("output"):
        sys.stdout.write(resp["output"])
    if resp.get("result"):
        sys.stdout.write(resp["result"] + "\n")


if __name__ == "__main__":
    main()
