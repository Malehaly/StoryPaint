"""BlenderKritaBridge — round-trip Grease Pencil drawings between Blender and Krita.

This is the Blender addon entry point. It must stay importable **without**
Blender so `core/` and `domain/` can be unit-tested headless with `pytest`.

Therefore: **no `import bpy` at module top level** — all Blender integration is
lazily imported inside `register()` / `unregister()`.
"""

bl_info = {
    "name": "StoryPaint",
    "author": "StoryPaint",
    "version": (1, 0, 1),
    "blender": (5, 2, 0),
    "location": "3D Viewport > Sidebar",
    "description": (
        "Send Grease Pencil drawings to Krita and bring the edits back to the "
        "same object (identity, layers, transform and location preserved)."
    ),
    "category": "Import-Export",
}


def register():
    """Register the addon inside Blender (lazy import; requires bpy)."""
    from .blender import register as _register_blender

    _register_blender()


def unregister():
    """Unregister the addon inside Blender (lazy import; requires bpy)."""
    from .blender import unregister as _unregister_blender

    _unregister_blender()


__all__ = ["bl_info", "register", "unregister"]
