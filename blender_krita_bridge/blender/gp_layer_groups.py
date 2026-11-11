"""Group Grease Pencil layer-transform channels in the Dope Sheet.

Blender shows keyed Grease Pencil layer transforms (``layers["Name"].translation``
etc.) as flat channels named "X Translation (Name)". Grouping those FCurves into
an ``ActionGroup`` named ``Layer Transform (<layer>)`` makes the Dope Sheet show
one collapsible header per layer — like the "Transform" group that object
channels get — collapsed by default (instead of "all expanded").

The grouping runs automatically (deferred file-load handler) and can also be
triggered by hand with ``bridge.group_layer_transforms``.
"""

from __future__ import annotations

import re

import bpy

_LAYER_RE = re.compile(r'^layers\["([^"]+)"\]\.(translation|rotation|scale)$')


def _ensure_grouped(gpd) -> int:
    """Assign layer-transform fcurves to ``Layer Transform (<name>)`` groups.

    Returns the number of changes (new groups + newly assigned channels), used
    to keep the depsgraph handler cheap and non-reentrant.
    """
    ad = gpd.animation_data
    if not ad or not ad.action:
        return 0
    action = ad.action
    changed = 0
    for action_layer in action.layers:
        for strip in action_layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    m = _LAYER_RE.match(fc.data_path)
                    if not m:
                        continue
                    name = f"Layer Transform ({m.group(1)})"
                    group = next((g for g in bag.groups if g.name == name), None)
                    if group is None:
                        group = bag.groups.new(name)
                        group.show_expanded = False  # collapsed by default
                        changed += 1
                    if fc.group != group:
                        fc.group = group
                        changed += 1
    return changed


def group_all(scene=None) -> int:
    """Group layer transforms for every Grease Pencil object in the scene."""
    if scene is None:
        scene = bpy.context.scene
    total = 0
    for obj in scene.objects:
        if obj.type == "GREASEPENCIL":
            try:
                total += _ensure_grouped(obj.data)
            except Exception:  # noqa: BLE001
                pass
    return total


class BRIDGE_OT_group_layer_transforms(bpy.types.Operator):
    """Group each layer's transform channels under 'Layer Transform (<name>)'."""
    bl_idname = "bridge.group_layer_transforms"
    bl_label = "Group Layer Transforms"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        n = group_all(context.scene)
        self.report({"INFO"}, f"Grouped {n} layer-transform channel(s)")
        return {"FINISHED"}


@bpy.app.handlers.persistent
def _on_load_post(*_args):
    try:
        group_all()  # Blender 5.x passes the filepath; group_all reads bpy.context.scene
    except Exception:  # noqa: BLE001
        pass


def register() -> None:
    bpy.utils.register_class(BRIDGE_OT_group_layer_transforms)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister() -> None:
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    bpy.utils.unregister_class(BRIDGE_OT_group_layer_transforms)
