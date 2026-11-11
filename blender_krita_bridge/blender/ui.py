"""Sidebar panel + Outliner context menu for BlenderKritaBridge (requires bpy)."""

from __future__ import annotations

import bpy

from . import export_image_planes, krita_check


class VIEW3D_PT_bridge(bpy.types.Panel):
    bl_label = "StoryPaint"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "StoryPaint"

    def draw(self, context):
        layout = self.layout
        status = krita_check.check_status()

        # ── Section 1: Krita side (setup + check) ──
        box = layout.box()
        row = box.row(align=True)
        row.label(text="Krita Side")
        row.operator("bridge.check_krita_side", icon="FILE_REFRESH")
        krita_check.draw_status_block(box, status)
        box.operator(
            "wm.url_open", text="Installation guide (README)", icon="URL"
        ).url = krita_check.INSTALL_GUIDE_URL

        layout.separator()

        # ── Section 2: Blender startup workspace (always available) ──
        box = layout.box()
        box.operator("bridge.load_startup", icon="FILE_NEW")

        layout.separator()

        # ── Section 3: Export (unlocked once the Krita side is ready) ──
        box = layout.box()
        box.enabled = status["ready"]
        box.operator("bridge.export_package")
        box.operator("bridge.export_image_planes")
        if not status["ready"]:
            box.label(text="Enable the Krita side to unlock export", icon="LOCKED")


class BRIDGE_OT_toggle_gp_draw(bpy.types.Operator):
    """Toggle between Object Mode and Draw Mode for the active Grease Pencil."""
    bl_idname = "bridge.toggle_gp_draw"
    bl_label = "Toggle Grease Pencil Draw Mode"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "GREASEPENCIL"

    def execute(self, context):
        obj = context.object
        if obj.mode == "PAINT_GREASE_PENCIL":
            bpy.ops.object.mode_set(mode="OBJECT")
        else:
            bpy.ops.object.mode_set(mode="PAINT_GREASE_PENCIL")
        return {"FINISHED"}


def _outliner_export_menu(self, context):
    """Right-click in the Outliner: quick Export to Krita for GP / image planes.

    The Outliner activates + selects the clicked object before opening
    ``OUTLINER_MT_object`` (see ``do_outliner_operation_event`` in Blender's
    ``outliner_tools.cc``), so ``context.object`` is the object under the cursor.
    """
    layout = self.layout
    obj = context.object
    if obj is None:
        return
    if obj.type == "GREASEPENCIL":
        layout.operator(
            "bridge.export_package", text="Export GP to Krita"
        ).object_name = obj.name
        layout.separator()
    elif export_image_planes._is_bridge_plane(obj):
        layout.operator(
            "bridge.export_image_planes", text="Export Image Plane to Krita"
        ).object_name = obj.name
        layout.separator()


classes = (VIEW3D_PT_bridge, BRIDGE_OT_toggle_gp_draw)

_addon_keymaps = []


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.OUTLINER_MT_object.prepend(_outliner_export_menu)
    _register_keymap()


def unregister():
    _unregister_keymap()
    try:
        bpy.types.OUTLINER_MT_object.remove(_outliner_export_menu)
    except ValueError:
        pass  # not prepended (e.g. first load of an older version)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


def _register_keymap():
    """Bind TAB to toggle Object <-> Draw Mode, but only for Grease Pencil.

    The operator's ``poll`` gates it to GP objects, so for every other object
    type the keymap item's poll fails and Blender falls through to the built-in
    TAB behaviour (object <-> edit, etc.).
    """
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if not kc:
        return
    for km_name in ("Object Non-modal", "Grease Pencil Draw Mode"):
        km = kc.keymaps.get(km_name)
        if km is None:
            km = kc.keymaps.new(name=km_name, space_type="EMPTY")
        kmi = km.keymap_items.new(
            BRIDGE_OT_toggle_gp_draw.bl_idname, type="TAB", value="PRESS"
        )
        _addon_keymaps.append((km, kmi))


def _unregister_keymap():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:  # noqa: BLE001
            pass
    _addon_keymaps.clear()
