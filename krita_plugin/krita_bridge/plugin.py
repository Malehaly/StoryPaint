"""BlenderKritaBridge Krita extension.

Defines the ``Extension`` subclass Krita instantiates when the plugin loads.
"""

from krita import Extension

from . import layer_menu


class BlenderKritaBridgeExtension(Extension):
    """Extension Krita instantiates when the plugin is enabled."""

    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        """Called once after Krita finishes loading the plugin."""
        # Start the layer context-menu hook (a poller, so it doesn't matter
        # whether the Layers docker exists yet).
        layer_menu.install_when_ready()

    def createActions(self, window):
        """Create per-window actions; the Docker holds the controls."""
        layer_menu.install()
