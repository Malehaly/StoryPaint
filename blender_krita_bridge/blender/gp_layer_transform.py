"""G/R/S in Draw mode transform the Grease Pencil LAYER (not the object).

Outside Draw mode, G/R/S move/rotate/scale the object as usual. Inside Draw mode
this module rebinds G (move), R (rotate) and S (scale) to modal operators that
transform the active layer's ``translation``/``rotation``/``scale`` instead, so
layer moves can be auto-keyed quickly (with the ``gp_layer_autokey`` handler).
"""

from __future__ import annotations

import math

import bpy
from mathutils import Euler, Matrix, Vector
from bpy_extras import view3d_utils

from . import gp_layer_groups


def _active_layer(context):
    obj = context.object
    if obj is None or obj.type != "GREASEPENCIL" or obj.mode != "PAINT_GREASE_PENCIL":
        return None
    return obj.data.layers.active


class BRIDGE_OT_move_gp_layer(bpy.types.Operator):
    """Move the active Grease Pencil layer (G in Draw mode)."""
    bl_idname = "bridge.move_gp_layer"
    bl_label = "Move Grease Pencil Layer"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_layer(context) is not None

    def invoke(self, context, event):
        self._layer = _active_layer(context)
        self._obj = context.object
        self._orig = Vector(self._layer.translation)
        # Depth plane = current world position of the layer origin, so the layer
        # stays under the cursor at its real depth (same feel as object-mode G).
        self._depth = self._obj.matrix_world @ self._orig
        self._start_world = view3d_utils.region_2d_to_location_3d(
            context.region,
            context.region_data,
            (event.mouse_region_x, event.mouse_region_y),
            self._depth,
        )
        if self._start_world is None:
            self._start_world = self._depth.copy()
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "MOUSEMOVE":
            cur = view3d_utils.region_2d_to_location_3d(
                context.region,
                context.region_data,
                (event.mouse_region_x, event.mouse_region_y),
                self._depth,
            )
            if cur is None:
                return {"RUNNING_MODAL"}
            delta_world = cur - self._start_world
            delta_local = self._obj.matrix_world.inverted().to_3x3() @ delta_world
            self._layer.translation = self._orig + delta_local
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            gp_layer_groups.group_all(context.scene)
            return {"FINISHED"}
        if event.type in {"RIGHTMOUSE", "ESC"}:
            self._layer.translation = self._orig
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


class BRIDGE_OT_rotate_gp_layer(bpy.types.Operator):
    """Rotate the active Grease Pencil layer around the mouse pivot (R in Draw mode).

    Rotates around the layer's LOCAL Y axis (the view axis for a front-facing
    Grease Pencil, so the drawing spins in its own plane instead of flipping
    edge-on like a Z rotation does). The rotation centre is the mouse position
    projected onto the layer's plane at the start of the drag.
    """
    bl_idname = "bridge.rotate_gp_layer"
    bl_label = "Rotate Grease Pencil Layer"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_layer(context) is not None

    def invoke(self, context, event):
        self._layer = _active_layer(context)
        self._obj = context.object
        self._orig_rotation = self._layer.rotation.copy()
        self._orig_translation = Vector(self._layer.translation)
        # Pivot = the mouse position projected onto the layer's plane (the view
        # plane through the layer origin), expressed in object-local space.
        depth = self._obj.matrix_world @ self._orig_translation
        self._pivot_world = view3d_utils.region_2d_to_location_3d(
            context.region,
            context.region_data,
            (event.mouse_region_x, event.mouse_region_y),
            depth,
        )
        if self._pivot_world is None:
            self._pivot_world = depth.copy()
        self._pivot_local = self._obj.matrix_world.inverted() @ self._pivot_world
        self._start_angle = self._screen_angle(context, event)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _screen_angle(self, context, event):
        """Angle of the mouse around the pivot, in screen space (radians)."""
        pivot_screen = view3d_utils.location_3d_to_region_2d(
            context.region, context.region_data, self._pivot_world
        )
        if pivot_screen is None:
            return 0.0
        dx = event.mouse_region_x - pivot_screen[0]
        dy = event.mouse_region_y - pivot_screen[1]
        return math.atan2(dy, dx)

    def modal(self, context, event):
        if event.type == "MOUSEMOVE":
            theta = self._screen_angle(context, event) - self._start_angle
            # Rotate around the object-local Y axis, about the mouse pivot:
            #   R' = Ry(theta) @ R0
            #   T' = Ry(theta) @ T0 + (I - Ry(theta)) @ P
            ry = Matrix.Rotation(theta, 3, (0.0, 1.0, 0.0))
            new_rot = ry @ self._orig_rotation.to_matrix()
            new_trans = ry @ self._orig_translation + (
                Matrix.Identity(3) - ry
            ) @ self._pivot_local
            self._layer.rotation = new_rot.to_euler()
            self._layer.translation = new_trans
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            gp_layer_groups.group_all(context.scene)
            return {"FINISHED"}
        if event.type in {"RIGHTMOUSE", "ESC"}:
            self._layer.rotation = self._orig_rotation.copy()
            self._layer.translation = self._orig_translation.copy()
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


class BRIDGE_OT_scale_gp_layer(bpy.types.Operator):
    """Scale the active Grease Pencil layer (S in Draw mode)."""
    bl_idname = "bridge.scale_gp_layer"
    bl_label = "Scale Grease Pencil Layer"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_layer(context) is not None

    def invoke(self, context, event):
        self._layer = _active_layer(context)
        self._start_y = event.mouse_region_y
        self._orig = tuple(self._layer.scale)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "MOUSEMOVE":
            dy = event.mouse_region_y - self._start_y
            factor = max(0.0, 1.0 - dy * 0.01)
            self._layer.scale = (
                self._orig[0] * factor,
                self._orig[1] * factor,
                self._orig[2] * factor,
            )
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            gp_layer_groups.group_all(context.scene)
            return {"FINISHED"}
        if event.type in {"RIGHTMOUSE", "ESC"}:
            self._layer.scale = self._orig
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


class GP_LAYER_PT_bridge_transform(bpy.types.Panel):
    """Per-layer transforms grouped under one name, like the Object Transform panel.

    Shows every Grease Pencil layer as its own box ``Layer Transform (<name>)``
    with the layer's translation / rotation / scale (x, y, z) side by side.
    """
    bl_idname = "GP_LAYER_PT_bridge_layer_transform"
    bl_label = "Layer Transform"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is None or obj.type != "GREASEPENCIL":
            return False
        gpd = obj.data
        return gpd is not None and len(gpd.layers) > 0

    def draw(self, context):
        gpd = context.object.data
        layout = self.layout
        layout.operator("bridge.group_layer_transforms", icon="GROUP")
        layout.separator()
        layout.use_property_split = True
        for layer in gpd.layers:
            box = layout.box()
            box.label(text=f"Layer Transform ({layer.name})")
            col = box.column(align=True)
            col.prop(layer, "translation")
            col.prop(layer, "rotation")
            col.prop(layer, "scale")


classes = (
    BRIDGE_OT_move_gp_layer,
    BRIDGE_OT_rotate_gp_layer,
    BRIDGE_OT_scale_gp_layer,
    GP_LAYER_PT_bridge_transform,
)

_addon_keymaps = []


def _register_keymap():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if not kc:
        return
    km = kc.keymaps.get("Grease Pencil Draw Mode")
    if km is None:
        km = kc.keymaps.new(name="Grease Pencil Draw Mode", space_type="EMPTY")
    for key, idname in (
        ("G", "bridge.move_gp_layer"),
        ("R", "bridge.rotate_gp_layer"),
        ("S", "bridge.scale_gp_layer"),
    ):
        kmi = km.keymap_items.new(idname, type=key, value="PRESS")
        _addon_keymaps.append((km, kmi))


def _unregister_keymap():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:  # noqa: BLE001
            pass
    _addon_keymaps.clear()


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)
    _register_keymap()


def unregister() -> None:
    _unregister_keymap()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
