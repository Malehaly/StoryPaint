# Krita MCP

A tiny socket server that runs **inside Krita** as a Python plugin and lets an
external tool (such as VS Code) execute Python code in Krita's embedded
interpreter, on the GUI thread.

This is a small development utility used to test and drive StoryPaint's Krita
side. It is independent of the StoryPaint plugin itself.

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

## Testing without Krita

`test_server_standalone.py` exercises the socket/exec logic without Krita or
PyQt5 (it loads `server.py` directly, bypassing the `krita` import).

```bash
python test_server_standalone.py
```
