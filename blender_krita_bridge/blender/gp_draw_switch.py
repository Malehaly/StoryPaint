"""Storyboard mode-following: keep the right object in the right mode.

Blender's Draw mode is per-object. This module follows the active object so you
don't have to keep switching modes by hand:

  * ``bridge.cycle_gp`` (Page Down / Page Up in Draw mode) cycles to the
    next/previous Grease Pencil and stays in Draw mode.
  * A low-frequency poller applies the "natural" mode of the active object:
    Grease Pencil always enters Draw mode, and Text/Camera drop back to Object
    mode (they have no Draw-mode tools), so clicking between them in the
    Outliner just works.
"""

from __future__ import annotations

import bpy

from . import animated_text

POLL_INTERVAL = 0.15  # seconds


def _gps(context=None):
    scene = bpy.context.scene if context is None else context.scene
    gps = [o for o in scene.objects if o.type == "GREASEPENCIL"]
    # Order by the OBJECT name (what the user sees/organizes in the Outliner),
    # NOT the creation order (which follows the auto "GPencil.NNN" numbering).
    return sorted(gps, key=lambda o: o.name.lower())


def _is_draw(obj) -> bool:
    return obj is not None and obj.type == "GREASEPENCIL" and obj.mode == "PAINT_GREASE_PENCIL"


def _select_only(context, obj) -> None:
    """Make ``obj`` the only selected Grease Pencil (selection follows draw)."""
    for o in context.scene.objects:
        if o.type == "GREASEPENCIL":
            o.select_set(o == obj)


class BRIDGE_OT_cycle_gp(bpy.types.Operator):
    """Switch to the next/previous Grease Pencil, staying in Draw mode."""
    bl_idname = "bridge.cycle_gp"
    bl_label = "Cycle Grease Pencil"
    bl_options = {"REGISTER", "UNDO"}

    direction: bpy.props.IntProperty(default=1)

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "GREASEPENCIL"

    def execute(self, context):
        gps = _gps(context)
        if len(gps) < 2:
            self.report({"WARNING"}, "Only one Grease Pencil in the scene")
            return {"CANCELLED"}
        cur = context.object
        try:
            idx = gps.index(cur)
        except ValueError:
            idx = -1 if self.direction < 0 else 0
        target = gps[(idx + self.direction) % len(gps)]
        was_draw = cur.mode == "PAINT_GREASE_PENCIL"
        context.view_layer.objects.active = target
        # Selection follows the draw target, so the Outliner highlight and the
        # orange selected-stroke tint don't stay on the previous GP.
        _select_only(context, target)
        if was_draw and target.mode != "PAINT_GREASE_PENCIL":
            bpy.ops.object.mode_set(mode="PAINT_GREASE_PENCIL")
        return {"FINISHED"}


class BRIDGE_OT_gp_layer_cycle(bpy.types.Operator):
    """Switch to the previous/next Grease Pencil layer of the active object."""
    bl_idname = "bridge.gp_layer_cycle"
    bl_label = "Cycle Grease Pencil Layer"
    bl_options = {"REGISTER", "UNDO"}

    direction: bpy.props.IntProperty(default=1)

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "GREASEPENCIL"

    def execute(self, context):
        gpd = context.object.data
        layers = list(gpd.layers)
        if len(layers) < 2:
            return {"CANCELLED"}
        active = gpd.layers.active
        if active is None:
            gpd.layers.active = layers[0]
            return {"FINISHED"}
        try:
            idx = layers.index(active)
        except ValueError:
            idx = 0
        gpd.layers.active = layers[(idx + self.direction) % len(layers)]
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Auto-follow poller
# --------------------------------------------------------------------------- #
_prev_active_name = None
_prev_selected = None  # frozenset of selected object names


def _any_draw(scene) -> bool:
    return any(_is_draw(o) for o in scene.objects)


def _current_selection(scene):
    return frozenset(o.name for o in scene.objects if o.select_get())


def _apply_natural_mode(focus, scene) -> None:
    """Put ``focus`` in its natural mode (GP -> Draw, Text/Camera -> Object)."""
    if focus.type == "GREASEPENCIL":
        if focus.mode != "PAINT_GREASE_PENCIL":
            try:
                bpy.ops.object.mode_set(mode="PAINT_GREASE_PENCIL")
                _select_only(bpy.context, focus)
            except Exception:  # noqa: BLE001
                pass
    elif focus.type in ("FONT", "CAMERA"):
        # Text/Camera have no Draw tools: leave Draw mode if a GP is in it.
        if _any_draw(scene):
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:  # noqa: BLE001
                pass


def _poll():
    """Follow the active/selected object into its natural mode.

    Two triggers:
      * the ACTIVE object changed (normal path);
      * the SELECTION changed while the active object stayed the same — this is
        what an Outliner click does while in Draw mode (it only re-selects, it
        does not re-activate), so we activate the newly-selected object and then
        apply its natural mode.

    - Grease Pencil -> Draw mode (always).
    - Text / Camera -> Object mode (only if some GP is currently in Draw mode).
    """
    global _prev_active_name, _prev_selected
    try:
        vl = bpy.context.view_layer
        scene = bpy.context.scene
        obj = vl.objects.active
        selected = _current_selection(scene)

        focus = None
        if obj is None:
            _prev_active_name = None
        elif obj.name != _prev_active_name:
            focus = obj
            _prev_active_name = obj.name
        elif _prev_selected is not None and selected != _prev_selected:
            added = selected - _prev_selected
            if len(added) == 1:
                name = next(iter(added))
                candidate = scene.objects.get(name)
                if candidate is not None:
                    vl.objects.active = candidate
                    focus = candidate
                    _prev_active_name = candidate.name

        if focus is not None:
            _apply_natural_mode(focus, scene)
            # When a camera becomes active, also select its attached subtitle
            # FONT so its cue keyframes appear in the Dope Sheet.
            if focus.type == "CAMERA":
                sub = animated_text.attached_subtitle(focus)
                if sub is not None:
                    sub.select_set(True)

        _prev_selected = _current_selection(scene)
    except Exception:  # noqa: BLE001
        pass
    return POLL_INTERVAL


classes = (BRIDGE_OT_cycle_gp, BRIDGE_OT_gp_layer_cycle)

_addon_keymaps = []


def _register_keymap():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if not kc:
        return
    # Page Down / Page Up in Draw mode cycle GP objects.
    km = kc.keymaps.get("Grease Pencil Draw Mode")
    if km is None:
        km = kc.keymaps.new(name="Grease Pencil Draw Mode", space_type="EMPTY")
    kmi = km.keymap_items.new("bridge.cycle_gp", type="PAGE_DOWN", value="PRESS")
    kmi.properties.direction = 1
    _addon_keymaps.append((km, kmi))
    kmi2 = km.keymap_items.new("bridge.cycle_gp", type="PAGE_UP", value="PRESS")
    kmi2.properties.direction = -1
    _addon_keymaps.append((km, kmi2))

    # Up/Down arrows in the Dope Sheet / Sequencer / Grease Pencil editors switch
    # the active GP layer (poll-gated, so a non-GP active object keeps the built-in
    # "jump to keyframe" behaviour).
    for km_name, space_type in (
        ("Dopesheet", "DOPESHEET_EDITOR"),
        ("Sequencer", "SEQUENCE_EDITOR"),
        ("Grease Pencil", "EMPTY"),
    ):
        km = kc.keymaps.get(km_name)
        if km is None:
            km = kc.keymaps.new(name=km_name, space_type=space_type)
        kmi = km.keymap_items.new("bridge.gp_layer_cycle", type="UP_ARROW", value="PRESS")
        kmi.properties.direction = 1  # up the list = higher index (front layer)
        _addon_keymaps.append((km, kmi))
        kmi2 = km.keymap_items.new("bridge.gp_layer_cycle", type="DOWN_ARROW", value="PRESS")
        kmi2.properties.direction = -1  # down the list = lower index (back layer)
        _addon_keymaps.append((km, kmi2))


def _unregister_keymap():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:  # noqa: BLE001
            pass
    _addon_keymaps.clear()


@bpy.app.handlers.persistent
def _on_load_post(*_args):
    """Re-register the poll timer after a .blend load / new file.

    Loading a file clears Blender's timer table, which silently kills the poll
    timer (the addon's ``register()`` does NOT re-run). ``@persistent`` is
    required so this handler itself survives ``File > New``.

    NOTE: Blender 5.x passes the FILEPATH (str) as the first argument to
    ``load_post`` handlers — NOT the scene — so read the scene from
    ``bpy.context``.
    """
    global _prev_active_name, _prev_selected
    try:
        scene = bpy.context.scene
    except Exception:  # noqa: BLE001
        scene = None
    try:
        obj = bpy.context.view_layer.objects.active
    except Exception:  # noqa: BLE001
        obj = None
    _prev_active_name = obj.name if obj is not None else None
    if obj is not None and obj.type == "CAMERA":
        sub = animated_text.attached_subtitle(obj)
        if sub is not None:
            sub.select_set(True)
    _prev_selected = _current_selection(scene) if scene is not None else None
    if not bpy.app.timers.is_registered(_poll):
        bpy.app.timers.register(_poll, first_interval=POLL_INTERVAL)


def register() -> None:
    global _prev_active_name, _prev_selected
    # bpy.context.object is NOT available in the restricted context used during
    # addon registration — read the view-layer active object instead.
    try:
        obj = bpy.context.view_layer.objects.active
    except Exception:  # noqa: BLE001
        obj = None
    _prev_active_name = obj.name if obj is not None else None
    # bpy.context.scene is ALSO unavailable in the restricted context; the first
    # poll establishes the selection baseline.
    _prev_selected = None
    for cls in classes:
        bpy.utils.register_class(cls)
    _register_keymap()
    if not bpy.app.timers.is_registered(_poll):
        bpy.app.timers.register(_poll, first_interval=POLL_INTERVAL)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister() -> None:
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if bpy.app.timers.is_registered(_poll):
        bpy.app.timers.unregister(_poll)
    _unregister_keymap()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
