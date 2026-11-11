"""Krita MCP plugin entry point.

Enable this plugin in Krita's Python Plugin Manager to expose a socket server
that VS Code can drive via `krita_mcp_client.py`.
"""

from krita import Extension, Krita


class KritaMcpExtension(Extension):
    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        from .server import start

        start()

    def createActions(self, window):
        pass


Krita.instance().addExtension(KritaMcpExtension(Krita.instance()))
