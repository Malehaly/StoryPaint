"""Auto-key Grease Pencil layer transforms when auto-keying is enabled.

Blender's built-in auto-key (``tool_settings.use_keyframe_insert_auto``) covers
object transforms but NOT Grease Pencil layer transforms (``translation``,
``rotation``, ``scale`` on ``gpd.layers``). This module watches layer transforms
via a depsgraph handler and inserts keyframes when they change and auto-key is
on, matching the object-transform behaviour. Only LAYER transforms are tracked —
moving the whole object does NOT key a layer.
"""

from __future__ import annotations

import bpy

_last = {}  # obj.name -> {layer.name -> (translation, rotation, scale)}
_last_frame = {}  # scene.name -> int (last seen frame)
_suspended = False


def suspend() -> None:
    """Pause auto-keying (used during export, which temporarily zeroes transforms)."""
    global _suspended
    _suspended = True


def resume() -> None:
    """Resume auto-keying and drop the cache (transforms changed off-frame)."""
    global _suspended
    _suspended = False
    _last.clear()
    _last_frame.clear()


def _vec(v) -> tuple:
    return tuple(round(float(x), 6) for x in v)


def _find_fcurve(gpd, layer_name: str, prop: str, axis: int):
    """Return the fcurve for ``layers["<name>"].<prop>`` axis, or None."""
    ad = gpd.animation_data
    if not ad or not ad.action:
        return None
    data_path = f'layers["{layer_name}"].{prop}'
    for action_layer in ad.action.layers:
        for strip in action_layer.strips:
            if strip.type != "KEYFRAME":
                continue
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    if fc.data_path == data_path and fc.array_index == axis:
                        return fc
    return None


def _key_transform_channel(gpd, layer, layer_name, prop, frame, start_frame, old_vals) -> None:
    """Key the current transform value at ``frame`` as a CONSTANT hold.

    Also inserts a baseline keyframe at ``start_frame`` (holding the pre-edit
    value in ``old_vals``) when the channel has no keyframe before ``frame``, so
    editing at a later frame does NOT move the earlier frames.
    """
    try:
        layer.keyframe_insert(data_path=prop, frame=frame)
    except Exception:  # noqa: BLE001
        return
    for axis in range(3):
        fc = _find_fcurve(gpd, layer_name, prop, axis)
        if fc is None:
            continue
        if start_frame < frame and not any(kp.co[0] < frame for kp in fc.keyframe_points):
            try:
                # NOTE: don't pass options={"REPLACE"} — it silently does nothing
                # when there's no keyframe at that frame (Blender 5.2).
                fc.keyframe_points.insert(start_frame, old_vals[axis])
            except Exception:  # noqa: BLE001
                pass
        for kp in fc.keyframe_points:
            kp.interpolation = "CONSTANT"


def _autokey(scene) -> None:
    if _suspended or not scene.tool_settings.use_keyframe_insert_auto:
        return
    frame = scene.frame_current
    scene_name = scene.name
    frame_changed = scene_name in _last_frame and _last_frame[scene_name] != frame
    _last_frame[scene_name] = frame

    for obj in scene.objects:
        if obj.type != "GREASEPENCIL":
            continue
        gpd = obj.data
        layers = {l.name: l for l in gpd.layers}
        cur = {
            name: (_vec(l.translation), _vec(l.rotation), _vec(l.scale))
            for name, l in layers.items()
        }
        prev = _last.get(obj.name)
        if prev is None or frame_changed:
            # First sight or the frame moved (animation playback): a change here
            # is the ANIMATION driving the transform, not the user editing it —
            # only refresh the cache, never key.
            _last[obj.name] = cur
            continue
        for name, (t, r, s) in cur.items():
            p = prev.get(name)
            if p is None:
                continue
            pt, pr, ps = p
            old_vals = {"translation": pt, "rotation": pr, "scale": ps}
            changed = [
                prop
                for prop, v, pv in (
                    ("translation", t, pt),
                    ("rotation", r, pr),
                    ("scale", s, ps),
                )
                if v != pv
            ]
            if changed:
                layer = layers.get(name)
                if layer is not None:
                    for prop in changed:
                        _key_transform_channel(
                            gpd, layer, name, prop, frame, scene.frame_start,
                            old_vals[prop],
                        )
        _last[obj.name] = cur


@bpy.app.handlers.persistent
def _on_depsgraph_update(scene, depsgraph):
    try:
        _autokey(scene)
    except Exception:  # noqa: BLE001
        pass


@bpy.app.handlers.persistent
def _on_load_pre(*_args):
    _last.clear()
    _last_frame.clear()


@bpy.app.handlers.persistent
def _on_load_post(scene, *_args):
    _last.clear()
    _last_frame.clear()


def register() -> None:
    if _on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)
    if _on_load_pre not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_on_load_pre)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    _last.clear()
    _last_frame.clear()


def unregister() -> None:
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
    if _on_load_pre in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_on_load_pre)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    _last.clear()
