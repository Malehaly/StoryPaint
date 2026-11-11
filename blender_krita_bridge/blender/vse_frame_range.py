"""Auto-sync VSE scene strips when a scene's frame range changes.

Blender's "Update Scene Frame Range" (right-click a scene strip in the
sequencer) re-syncs a scene strip's cached *content* length to the scene's
current ``frame_start``/``frame_end``. This module does that automatically via a
``depsgraph_update_post`` handler, so bumping a scene's frame range is reflected
in its scene strips without the extra right-click.

Blender 5.x note: a scene strip has TWO lengths —

* ``frame_duration`` (the *content*): for a scene strip this is cached from the
  referenced scene's range and is **read-only** from Python. The only way to
  update it is ``SEQUENCER_OT_scene_frame_range_update`` (sets ``strip->len``).
* ``duration`` / ``frame_final_duration`` (the *handles* / on-timeline length):
  writable.

Setting only ``duration`` stretches the handles while the content stays at the
old scene range, which is exactly the "half greyed" strip the user sees. The fix
is to do BOTH: update the content via the operator, and set ``duration`` so the
handles match. (The sequencer collection is ``scene.sequence_editor.strips``,
renamed from ``sequences`` in 4.x.)
"""

from __future__ import annotations

import bpy

_last_range = {}  # scene.name -> (frame_start, frame_end)


def _scene_strips_for(scene):
    """Yield ``(strip, owner_scene)`` for every VSE scene strip referencing ``scene``."""
    for other in bpy.data.scenes:
        sed = other.sequence_editor
        if sed is None:
            continue
        for strip in sed.strips:
            if getattr(strip, "type", "") == "SCENE" and strip.scene == scene:
                yield strip, other


def _sync_strip(strip, owner_scene, new_len) -> None:
    """Fully re-sync one scene strip: content AND on-timeline length."""
    sed = owner_scene.sequence_editor
    if sed is None:
        return
    prev_active = getattr(sed, "active_strip", None)
    try:
        # 1. Stretch the on-timeline handles to the new scene length.
        strip.duration = new_len
        # 2. Update the content (read-only frame_duration) via the operator,
        #    which sets strip->len and preserves the handles we just set.
        sed.active_strip = strip
        with bpy.context.temp_override(scene=owner_scene):
            bpy.ops.sequencer.scene_frame_range_update()
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            sed.active_strip = prev_active
        except Exception:  # noqa: BLE001
            pass


def sync_scene_strips(scene=None) -> None:
    """Update scene strips only when a scene's frame range actually changed.

    On first sight of a scene (e.g. right after a file load) the range is only
    remembered — strips are NOT touched, so split strips keep their split
    durations. Only a real change to ``frame_start``/``frame_end`` re-syncs.
    """
    scenes = [scene] if scene is not None else list(bpy.data.scenes)
    for sc in scenes:
        new_range = (sc.frame_start, sc.frame_end)
        old_range = _last_range.get(sc.name)
        if old_range is None:
            _last_range[sc.name] = new_range
            continue
        if old_range == new_range:
            continue
        _last_range[sc.name] = new_range
        new_len = sc.frame_end - sc.frame_start + 1
        for strip, owner in _scene_strips_for(sc):
            _sync_strip(strip, owner, new_len)


@bpy.app.handlers.persistent
def _on_depsgraph_update(scene, depsgraph):
    try:
        # Check all scenes (cheap) — the edited scene may not be the active one.
        sync_scene_strips()
    except Exception:  # noqa: BLE001
        pass


@bpy.app.handlers.persistent
def _on_load_post(scene, *_args):
    # Re-baseline on the newly loaded file WITHOUT touching strips (a split
    # strip must keep its split duration, not be reset to the full scene range).
    _last_range.clear()


def register() -> None:
    if _on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    _last_range.clear()  # baseline; the first depsgraph update remembers ranges


def unregister() -> None:
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    _last_range.clear()
