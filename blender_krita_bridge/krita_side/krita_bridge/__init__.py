"""Krita plugin entry point for BlenderKritaBridge.

Krita imports this package (from the ``pykrita`` resources directory) when the
plugin is enabled, and expects the module to register an ``Extension`` instance
and any dockers.
"""

from krita import DockWidgetFactory, DockWidgetFactoryBase, Krita

from . import bridge
from .docker import BridgeDocker
from .plugin import BlenderKritaBridgeExtension


def register_extension():
    app = Krita.instance()
    app.addExtension(BlenderKritaBridgeExtension(app))
    app.addDockWidgetFactory(
        DockWidgetFactory("bridge_docker", DockWidgetFactoryBase.DockRight, BridgeDocker)
    )
    bridge.start()


register_extension()
