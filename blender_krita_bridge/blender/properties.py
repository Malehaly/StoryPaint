"""Scene properties for the StoryPaint panel (bridge toggle, image storage)."""

from __future__ import annotations

import bpy

from . import connection


def _on_bridge_enabled(self, context):
    connection.set_bridge_enabled(bool(self.storypaint_bridge_enabled))


def register() -> None:
    bpy.types.Scene.storypaint_bridge_enabled = bpy.props.BoolProperty(
        name="Enable Bridge",
        description="Turn the local Blender–Krita bridge on or off",
        default=False,
        update=_on_bridge_enabled,
        options={"SKIP_SAVE"},
    )
    bpy.types.Scene.storypaint_image_storage = bpy.props.EnumProperty(
        name="Save images inside",
        description="Where the artwork returned from Krita is stored",
        items=[
            (
                "INTERNAL",
                "The .blend file",
                "Pack the returned images into the .blend file",
            ),
            (
                "EXTERNAL",
                "A folder next to the .blend file",
                "Store the returned images in a folder next to the .blend file",
            ),
        ],
        default="INTERNAL",
    )
    bpy.types.Scene.storypaint_show_config = bpy.props.BoolProperty(
        name="Configurations",
        description="Show StoryPaint configuration options",
        default=False,
    )


def unregister() -> None:
    for name in (
        "storypaint_bridge_enabled",
        "storypaint_image_storage",
        "storypaint_show_config",
    ):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
