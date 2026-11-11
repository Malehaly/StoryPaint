# Krita MCP

A tiny socket server that runs **inside Krita** as a Python plugin and lets an
external tool (such as VS Code) execute Python code in Krita's embedded
interpreter, on the GUI thread.

This is a small development utility used to test and drive StoryPaint's Krita
side. It is independent of the StoryPaint plugin itself.

> **Note:** despite the name, this tool does **not** implement the Model
> Context Protocol (MCP). It speaks a minimal, custom JSON-over-socket protocol
> with the bundled `krita_mcp_client.py` — it will not work with a generic MCP
> client.

## Install

1. Copy the `krita_mcp/` folder and `krita_mcp.desktop` into Krita's `pykrita`
   directory:
   - Windows: `%APPDATA%\krita\pykrita\`
   - Linux: `~/.local/share/krita/pykrita/`
   - macOS: `~/Library/Application Support/krita/pykrita/`
2. In Krita, open **Settings → Configure Krita → Python Plugin Manager**,
   enable **Krita MCP**, then restart Krita.

## Usage

```bash
# Run a one-liner in Krita
python krita_mcp_client.py -c "print(Krita.instance().version())"

# Run a script file
python krita_mcp_client.py -f script.py

# Pipe code from stdin
echo "print('hi')" | python krita_mcp_client.py
```

## How it works

- `krita_mcp/server.py` — TCP server on `127.0.0.1:9877`. A background thread
  accepts connections and queues `{code}` requests; a `QTimer` drains the queue
  on Krita's GUI thread and executes the code, capturing stdout/stderr.
- A `__result__` variable (if set) is returned as the result.
- The namespace persists between calls, so you can define a function once and
  call it later.
- `krita_mcp_client.py` — connects, sends code and prints the response.

## Security

`server.py` executes arbitrary Python code with the user's permissions. Treat it
as a development tool, not a hardened service:

- It listens **only on `127.0.0.1`** (loopback) and is never exposed to the
  network.
- It has **no authentication** — any local process can connect and send code.
- Enable the plugin only on trusted, single-user machines, and only while you
  actually need it; disable it when done.
- Do not forward the port or run it on shared or untrusted machines.

## Testing without Krita

`test_server_standalone.py` exercises the socket/exec logic without Krita or
PyQt5 (it loads `server.py` directly, bypassing the `krita` import).

```bash
python test_server_standalone.py
```
