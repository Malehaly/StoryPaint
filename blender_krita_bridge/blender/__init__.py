"""Blender integration for BlenderKritaBridge (requires `bpy`).

Imported lazily by the addon entry point (`blender_krita_bridge/__init__.py`)
so the core/domain layers stay headless-testable.
"""

from __future__ import annotations

from . import (
    animated_text,
    asset_library,
    connection,
    export_package,
    export_image_planes,
    gp_draw_switch,
    gp_layer_autokey,
    gp_layer_groups,
    gp_layer_transform,
    image_import,
    krita_check,
    load_startup,
    ui,
    vse_frame_range,
)


def register():
    """Register operators, panels, properties and start the bridge server."""
    asset_library.register()
    export_package.register()
    export_image_planes.register()
    krita_check.register()
    load_startup.register()
    ui.register()
    animated_text.register()
    connection.BridgeServer.instance().start()
    connection.register_timer()
    connection.register_handler()
    image_import.register_handler()
    vse_frame_range.register()
    gp_draw_switch.register()
    gp_layer_autokey.register()
    gp_layer_transform.register()
    gp_layer_groups.register()


def unregister():
    """Unregister operators, panels, properties and stop the bridge server."""
    gp_layer_groups.unregister()
    gp_layer_transform.unregister()
    gp_layer_autokey.unregister()
    gp_draw_switch.unregister()
    vse_frame_range.unregister()
    image_import.unregister_handler()
    connection.unregister_handler()
    connection.unregister_timer()
    connection.BridgeServer.instance().stop()
    animated_text.unregister()
    ui.unregister()
    load_startup.unregister()
    krita_check.unregister()
    asset_library.unregister()
    export_image_planes.unregister()
    export_package.unregister()
