"""Animatable dialogue/subtitle text for FONT (Text) objects.

Blender can't keyframe the text content of a ``FONT`` object directly, and
Blender 5.2 doesn't expose string F-Curve values to Python either (``evaluated_get``
always returns the first keyframe's value and the ``Keyframe`` RNA has no string
access). So this module keeps a Python-readable list of cues
(``obj["bridge_at_cues"]`` = ``[{"frame": int, "text": str}, ...]``) as the source
of truth, syncs ``TextCurve.body`` from it on every frame change, and lets you
key the current text with one click (or the ``I`` key, for FONT objects only).

It also:
  * Attaches the text to the active camera (bottom-centre) with a configurable
    text scale, wrap width (% of the frame) and X/Y offsets.
  * Draws an optional outline (a second, thicker text object behind the main
    text) with an adjustable thickness.
  * Exports/imports the cues as **SRT** (the standard subtitle format, plain
    text with timecodes) so dialogues can be translated externally.
"""

from __future__ import annotations

import bpy

CUE_PROP = "bridge_at_cues"
DEPTH = 5.0  # distance in front of the camera for camera-attached text
BOTTOM_MARGIN = 0.06  # fraction of frame height above the bottom edge

DEFAULT_SCALE = 0.120  # subtitle text object scale (uniform X/Y/Z)
DEFAULT_WRAP_PCT = 75.0  # % of the camera frame width the text wraps at
DEFAULT_OUTLINE_WIDTH = 0.030  # glyph offset (outline thickness) in font units
OUTLINE_SUFFIX = ".Outline"
OUTLINE_FLAG = "bridge_at_is_outline"
OUTLINE_COLOR = (0.0, 0.0, 0.0, 1.0)  # black outline


# --------------------------------------------------------------------------- #
# Cue list helpers
# --------------------------------------------------------------------------- #
def get_cues(obj) -> list:
    """Return the sorted list of cues ``[{"frame": int, "text": str}, ...]``.

    The stored ID-property dictionaries are not plain Python ``dict`` instances
    (they support ``.get()`` but fail ``isinstance(c, dict)``), so match on the
    ``.get`` attribute instead.
    """
    cues = obj.get(CUE_PROP)
    if not isinstance(cues, list):
        return []
    return sorted(
        (c for c in cues if hasattr(c, "get")),
        key=lambda c: int(c.get("frame", 0)),
    )


def set_cues(obj, cues) -> None:
    obj[CUE_PROP] = [
        {
            "frame": int(c.get("frame", 0)),
            "text": str(c.get("text", "")),
            "index": int(c.get("index", i)),
        }
        for i, c in enumerate(cues)
    ]


def attached_subtitle(obj):
    """Return the subtitle FONT attached to ``obj`` (a camera), or None.

    An attached subtitle is a direct child FONT with the attach flag or a cue
    list. The outline FONT is a child of the text (not of the camera), so it is
    not returned.
    """
    if obj is None:
        return None
    for child in obj.children:
        if child.type == "FONT" and (child.bridge_at_attach or CUE_PROP in child):
            return child
    return None


def text_at_frame(cues, frame: int) -> str:
    """Return the text to show at ``frame`` (constant hold between cues)."""
    current = ""
    for cue in cues:
        if int(cue.get("frame", 0)) <= frame:
            current = str(cue.get("text", ""))
        else:
            break
    return current


def frame_of_cue(cues, frame: int):
    """Return the cue dict at exactly ``frame``, or None."""
    for cue in cues:
        if int(cue.get("frame", 0)) == frame:
            return cue
    return None


def upsert_cue(obj, frame: int, text: str) -> int:
    """Add/replace a cue at ``frame``; return its stable index."""
    cues = [c for c in get_cues(obj) if int(c.get("frame", 0)) != frame]
    existing = [int(c.get("index", -1)) for c in cues]
    new_idx = (max(existing) + 1) if existing else 0
    cues.append({"frame": int(frame), "text": text, "index": new_idx})
    set_cues(obj, sorted(cues, key=lambda c: c["frame"]))
    return new_idx


def remove_cue(obj, frame: int) -> None:
    set_cues(obj, [c for c in get_cues(obj) if int(c.get("frame", 0)) != frame])


# --------------------------------------------------------------------------- #
# Camera attach helpers
# --------------------------------------------------------------------------- #
def _camera_frame_dims(scene, camera) -> tuple:
    """Return (width, height) of the camera view at ``DEPTH`` in front of it."""
    cam = camera.data
    frame = cam.view_frame(scene=scene)
    z_dist = abs(frame[0].z)
    if z_dist < 1e-6:
        z_dist = 1.0
    xs = [v.x for v in frame]
    ys = [v.y for v in frame]
    width = (max(xs) - min(xs)) * DEPTH / z_dist
    height = (max(ys) - min(ys)) * DEPTH / z_dist
    return width, height


def apply_camera_attach(obj, camera) -> None:
    """Parent ``obj`` to ``camera`` and place it at the bottom-centre.

    The text's front face (+Z) is made to face the camera, it is scaled so its
    wrapping width matches the camera's frame width, and it sits at the bottom
    of the frame (plus the configured offsets).
    """
    from mathutils import Matrix

    scene = bpy.context.scene
    td = obj.data
    width, height = _camera_frame_dims(scene, camera)

    td.align_x = "CENTER"
    td.align_y = "BOTTOM"

    # Text scale is user-controlled (independent of the wrap width): the default
    # 0.120 gives a readable subtitle height. The wrap width is a % of the camera
    # frame width, so the text box width (in local units) is derived from both.
    scale = max(0.0001, getattr(obj, "bridge_at_scale", DEFAULT_SCALE))
    wrap_pct = min(100.0, max(5.0, getattr(obj, "bridge_at_wrap_pct", DEFAULT_WRAP_PCT)))
    wrap_world = width * wrap_pct / 100.0
    box_width = wrap_world / scale
    td.text_boxes[0].width = box_width
    # Height must stay 0 (unlimited): a nonzero height shifts the glyphs far
    # below the object origin, which lands them at/behind the camera and makes
    # the text disappear from view.
    td.text_boxes[0].height = 0.0
    # Centre the box on the origin so align_x=CENTER centres the glyphs on the
    # object origin (the box otherwise spans [0, box_width] and the text sits
    # off to the right of the frame).
    td.text_boxes[0].x = -box_width / 2.0
    td.text_boxes[0].y = 0.0
    td.overflow = "NONE"  # keep wrapping; do not scale/truncate

    ox = getattr(obj, "bridge_at_offset_x", 0.0)
    oy = getattr(obj, "bridge_at_offset_y", 0.0)
    y = -height / 2.0 + height * BOTTOM_MARGIN + oy

    # Parent with an identity parent-inverse and explicit local transforms so
    # the text's +Z face (the readable side) points back at the camera. Setting
    # the full world matrix instead left the text 180°-rotated around X
    # (back-facing, hence invisible for flat extruded text).
    obj.parent = camera
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.rotation_mode = "XYZ"
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = (scale, scale, scale)
    obj.location = (ox, y, -DEPTH)
    sync_outline(obj)
    _disable_taa_for_subtitles(scene)


def detach_camera(obj) -> None:
    if obj.parent is not None:
        obj.parent = None


# --------------------------------------------------------------------------- #
# Outline (a second, thicker FONT object behind the main text)
# --------------------------------------------------------------------------- #
def _outline_obj(obj):
    """Return the outline child of ``obj``, or None."""
    for child in obj.children:
        if child.get(OUTLINE_FLAG):
            return child
    return None


def _get_outline_material():
    """Return the shared black emission material for outline copies."""
    mat = bpy.data.materials.get("bridge_at_outline_mat")
    if mat is None:
        mat = bpy.data.materials.new("bridge_at_outline_mat")
    if not mat.use_nodes:
        mat.use_nodes = True
    nt = mat.node_tree
    if not any(n.type == "EMISSION" for n in nt.nodes):
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        emis = nt.nodes.new("ShaderNodeEmission")
        emis.inputs[0].default_value = OUTLINE_COLOR
        nt.links.new(emis.outputs[0], out.inputs[0])
    return mat


def apply_outline(obj) -> None:
    """Create, refresh or remove the outline copy according to obj's settings."""
    from mathutils import Matrix

    out_obj = _outline_obj(obj)
    if getattr(obj, "bridge_at_outline", False):
        if out_obj is None:
            data = bpy.data.curves.new(obj.name + OUTLINE_SUFFIX, type="FONT")
            out_obj = bpy.data.objects.new(obj.name + OUTLINE_SUFFIX, data)
            out_obj[OUTLINE_FLAG] = True
            coll = obj.users_collection[0] if obj.users_collection else bpy.context.scene.collection
            coll.objects.link(out_obj)
            out_obj.parent = obj
            out_obj.matrix_parent_inverse = Matrix.Identity(4)
            out_obj.rotation_mode = "XYZ"
            out_obj.rotation_euler = (0.0, 0.0, 0.0)
            out_obj.scale = (1.0, 1.0, 1.0)
            out_obj.location = (0.0, 0.0, -0.01)  # just behind the fill
        mat = _get_outline_material()
        if not out_obj.data.materials:
            out_obj.data.materials.append(mat)
        elif out_obj.data.materials[0] != mat:
            out_obj.data.materials[0] = mat
        sync_outline(obj)
    elif out_obj is not None:
        data = out_obj.data
        bpy.data.objects.remove(out_obj, do_unlink=True)
        if data.users == 0:
            bpy.data.curves.remove(data)


def sync_outline(obj) -> bool:
    """Keep the outline copy's text, wrap and thickness in sync with ``obj``."""
    out_obj = _outline_obj(obj)
    if out_obj is None:
        return False
    td, tod = obj.data, out_obj.data
    changed = False
    if tod.body != td.body:
        tod.body = td.body
        changed = True
    for attr, val in (
        ("size", td.size),
        ("resolution_u", td.resolution_u),
        ("resolution_v", td.resolution_v),
        ("render_resolution_u", td.render_resolution_u),
        ("render_resolution_v", td.render_resolution_v),
        ("align_x", td.align_x),
        ("align_y", td.align_y),
        ("overflow", td.overflow),
        ("offset", getattr(obj, "bridge_at_outline_width", DEFAULT_OUTLINE_WIDTH)),
        ("space_line", td.space_line),
        ("space_word", td.space_word),
        ("space_character", td.space_character),
        ("font", td.font),
        ("font_bold", td.font_bold),
        ("font_italic", td.font_italic),
        ("font_bold_italic", td.font_bold_italic),
    ):
        if getattr(tod, attr) != val:
            setattr(tod, attr, val)
            changed = True
    if td.text_boxes and tod.text_boxes:
        for attr in ("width", "height", "x", "y"):
            v = getattr(td.text_boxes[0], attr)
            if getattr(tod.text_boxes[0], attr) != v:
                setattr(tod.text_boxes[0], attr, v)
                changed = True
    return changed


# --------------------------------------------------------------------------- #
# Frame-change sync
# --------------------------------------------------------------------------- #
def sync_all_font_objects(scene=None):
    """Sync every FONT object's body from its cue list for the current frame."""
    if scene is None:
        scene = bpy.context.scene
    frame = scene.frame_current
    for obj in bpy.data.objects:
        if obj.type != "FONT" or CUE_PROP not in obj:
            continue
        cues = get_cues(obj)
        # Keep cues in sync with the marker keyframes (Dope Sheet edits: move OR
        # delete a keyframe).
        if sync_cue_frames_from_markers(obj):
            cues = get_cues(obj)
        text = text_at_frame(cues, frame)  # "" when no cues remain
        if obj.data.body != text:
            obj.data.body = text
        sync_outline(obj)


@bpy.app.handlers.persistent
def _on_frame_change(scene, *_args):
    try:
        sync_all_font_objects(scene)
    except Exception as exc:  # noqa: BLE001
        print("BRIDGE: subtitle sync error:", type(exc).__name__, exc)


def _marker_fcurve(obj):
    """Return the FCurve driving ``["bridge_at_marker"]``, or None."""
    ad = obj.animation_data
    if ad is None or ad.action is None:
        return None
    action = ad.action
    # Blender 5.x stores FCurves in layered actions: layers -> strips -> channelbags.
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for bag in getattr(strip, "channelbags", []):
                for fc in getattr(bag, "fcurves", []):
                    if fc.data_path == '["bridge_at_marker"]':
                        return fc
    for fc in getattr(action, "fcurves", []):  # legacy fallback
        if fc.data_path == '["bridge_at_marker"]':
            return fc
    return None


def _marker_entries(obj):
    """Return ``[(frame, value), ...]`` of the marker FCurve keyframes."""
    fc = _marker_fcurve(obj)
    if fc is None:
        return []
    return [(round(k.co[0]), round(k.co[1])) for k in fc.keyframe_points]


def sync_cue_frames_from_markers(obj) -> bool:
    """Reconcile cues with the ``bridge_at_marker`` keyframes (move AND delete).

    Each marker keyframe's value is the cue's stable index. A cue whose index no
    longer has a marker was deleted in the Dope Sheet -> drop it; a cue whose
    marker moved -> re-time it. If the object has cues but no markers at all
    (SRT import), the cues are left untouched. Returns True if cues changed.
    """
    cues = get_cues(obj)
    if not cues:
        return False
    entries = _marker_entries(obj)  # [(frame, value)]
    if not entries:
        # No markers: SRT import -> cues are the source of truth. But if the
        # object was keyed through the plugin (the marker property exists), the
        # user deleted every keyframe -> clear the cues.
        if "bridge_at_marker" in obj:
            set_cues(obj, [])
            return True
        return False
    index_to_frame = {}
    for f, v in entries:
        index_to_frame[int(round(v))] = int(round(f))
    new_cues = []
    changed = False
    for c in cues:
        idx = int(c.get("index", -1))
        frame = index_to_frame.get(idx)
        if frame is None:
            changed = True  # this cue's marker was deleted
            continue
        if int(c.get("frame", 0)) != frame:
            changed = True  # this cue's marker moved
        new_cues.append({"frame": frame, "text": c.get("text", ""), "index": idx})
    if len(new_cues) != len(cues):
        changed = True
    if not changed:
        return False
    new_cues.sort(key=lambda c: c["frame"])
    set_cues(obj, new_cues)
    return True


@bpy.app.handlers.persistent
def _on_depsgraph_update(scene, depsgraph):
    """Re-sync subtitle cues/outlines when a FONT or its action is edited."""
    try:
        font_touched = False
        action_touched = False
        for update in depsgraph.updates:
            i = update.id
            if getattr(i, "id_type", "") == "ACTION":
                action_touched = True
            elif getattr(i, "id_type", "") == "OBJECT":
                o = getattr(i, "original", i)
                if getattr(o, "type", None) == "FONT":
                    font_touched = True
        if not (font_touched or action_touched):
            return
        for obj in bpy.data.objects:
            if obj.type != "FONT":
                continue
            if get_cues(obj) and sync_cue_frames_from_markers(obj):
                sync_all_font_objects(scene)
                return
            sync_outline(obj)
    except Exception:  # noqa: BLE001
        pass


def _disable_taa_for_subtitles(_scene=None) -> None:
    """Keep EEVEE TAA reprojection OFF on every scene.

    TAA reprojection reuses previous-frame samples, so discrete text changes
    (a subtitle appearing on a cue) ghost in the viewport. It is viewport-only
    (the final render is unaffected). The 2D anime workflow wants it ALWAYS off,
    so disable it on ALL scenes unconditionally (called on addon load, file
    load and camera attach).
    """
    try:
        for scene in bpy.data.scenes:
            ee = getattr(scene, "eevee", None)
            if ee is not None:
                ee.use_taa_reprojection = False
    except Exception:  # noqa: BLE001
        pass


@bpy.app.handlers.persistent
def _on_load_post(*_args):
    # Blender 5.x passes the FILEPATH (str) as the first arg, NOT the scene;
    # _disable_taa_for_subtitles reads bpy.context.scene when given None.
    _disable_taa_for_subtitles()


# --------------------------------------------------------------------------- #
# SRT export / import
# --------------------------------------------------------------------------- #
def _frame_to_srt_time(frame, fps) -> str:
    total = max(0.0, frame / max(fps, 1e-6))
    ms = int(round((total - int(total)) * 1000))
    if ms >= 1000:
        ms = 0
        total += 1.0
    s = int(total)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def _srt_time_to_frame(timestr, fps) -> int:
    # Accept "HH:MM:SS,mmm" or "HH:MM:SS.mmm".
    clean = timestr.strip().replace(".", ",")
    parts = clean.split(",")
    ms = 0
    if len(parts) == 2:
        ms = int(parts[1].ljust(3, "0")[:3])
    hms = parts[0].split(":")
    h, m, s = (int(x) for x in hms)
    seconds = h * 3600 + m * 60 + s + ms / 1000.0
    return int(round(seconds * fps))


def export_srt(obj, filepath: str, fps: float, end_frame: int) -> str:
    """Write the cue list as SRT; return a short summary string."""
    cues = get_cues(obj)
    blocks = []
    for i, cue in enumerate(cues):
        text = str(cue.get("text", "")).strip()
        if not text:
            continue
        start = int(cue.get("frame", 0))
        end = int(cues[i + 1].get("frame", end_frame + 1)) if i + 1 < len(cues) else end_frame + 1
        blocks.append((start, end, text))
    lines = []
    for idx, (start, end, text) in enumerate(blocks, start=1):
        lines.append(str(idx))
        lines.append(f"{_frame_to_srt_time(start, fps)} --> {_frame_to_srt_time(end, fps)}")
        lines.append(text)
        lines.append("")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return f"exported {len(blocks)} subtitle block(s) to {filepath}"


def import_srt(obj, filepath: str, fps: float) -> str:
    """Parse an SRT file into cues (a text cue at each start, empty at each end)."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    # Blocks are separated by blank lines; each block: index / time --> time / text.
    raw_blocks = [b.strip() for b in content.replace("\r\n", "\n").split("\n\n") if b.strip()]
    cues = []
    for block in raw_blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if len(lines) < 2:
            continue
        # Find the "-->" line.
        time_line = next((ln for ln in lines if "-->" in ln), None)
        if time_line is None:
            continue
        start_str, end_str = [p.strip() for p in time_line.split("-->", 1)]
        text = "\n".join(ln for ln in lines if ln.strip() != time_line and not ln.strip().isdigit()).strip()
        if not text:
            continue
        start = _srt_time_to_frame(start_str, fps)
        end = _srt_time_to_frame(end_str, fps)
        cues.append({"frame": start, "text": text})
        if end > start:
            cues.append({"frame": end, "text": ""})
    set_cues(obj, sorted(cues, key=lambda c: c["frame"]))
    return f"imported {len(cues)} cue(s) from {filepath}"


# --------------------------------------------------------------------------- #
# Operators
# --------------------------------------------------------------------------- #
def _insert_subtitle_keyframe(obj, scene) -> int:
    """Store the current body text as a cue at the current frame."""
    frame = scene.frame_current
    text = obj.data.body
    idx = upsert_cue(obj, frame, text)
    # A real keyframe on an int property so the timing shows in the Dope
    # Sheet. Its value is the cue's index, so moving the keyframe moves the
    # matching cue.
    obj["bridge_at_marker"] = idx
    obj.keyframe_insert(data_path='["bridge_at_marker"]', frame=frame)
    sync_outline(obj)
    return frame


class BRIDGE_OT_at_keyframe(bpy.types.Operator):
    """Store the current text as a cue at the current frame."""
    bl_idname = "bridge.at_keyframe"
    bl_label = "Insert Subtitle Keyframe"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "FONT"

    def execute(self, context):
        frame = _insert_subtitle_keyframe(context.object, context.scene)
        self.report({"INFO"}, f"Subtitle cue at frame {frame}")
        return {"FINISHED"}


class BRIDGE_OT_at_keyframe_attached(bpy.types.Operator):
    """Insert a cue on the subtitle attached to the active camera."""
    bl_idname = "bridge.at_keyframe_attached"
    bl_label = "Insert Subtitle Keyframe"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "CAMERA" and attached_subtitle(obj) is not None

    def execute(self, context):
        obj = attached_subtitle(context.object)
        frame = _insert_subtitle_keyframe(obj, context.scene)
        self.report({"INFO"}, f"Subtitle cue at frame {frame}")
        return {"FINISHED"}


def _delete_subtitle_keyframe(obj, scene) -> bool:
    """Remove the cue at the current frame, if any. Returns True if removed."""
    frame = scene.frame_current
    if frame_of_cue(get_cues(obj), frame) is None:
        return False
    remove_cue(obj, frame)
    fc = _marker_fcurve(obj)
    if fc is not None:
        for kp in list(fc.keyframe_points):
            if int(round(kp.co[0])) == frame:
                fc.keyframe_points.remove(kp, fast=True)
    return True


class BRIDGE_OT_at_delete(bpy.types.Operator):
    """Remove the cue at the current frame."""
    bl_idname = "bridge.at_delete"
    bl_label = "Delete Subtitle Keyframe"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "FONT"

    def execute(self, context):
        frame = context.scene.frame_current
        if _delete_subtitle_keyframe(context.object, context.scene):
            self.report({"INFO"}, f"Removed subtitle cue at frame {frame}")
        else:
            self.report({"WARNING"}, f"No subtitle cue at frame {frame}")
        sync_all_font_objects(context.scene)
        return {"FINISHED"}


class BRIDGE_OT_at_delete_attached(bpy.types.Operator):
    """Remove the cue on the subtitle attached to the active camera."""
    bl_idname = "bridge.at_delete_attached"
    bl_label = "Delete Subtitle Keyframe"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "CAMERA" and attached_subtitle(obj) is not None

    def execute(self, context):
        obj = attached_subtitle(context.object)
        frame = context.scene.frame_current
        if _delete_subtitle_keyframe(obj, context.scene):
            self.report({"INFO"}, f"Removed subtitle cue at frame {frame}")
        else:
            self.report({"WARNING"}, f"No subtitle cue at frame {frame}")
        sync_all_font_objects(context.scene)
        return {"FINISHED"}


class BRIDGE_OT_at_attach(bpy.types.Operator):
    """Parent the text to the camera and place it as a bottom subtitle."""
    bl_idname = "bridge.at_attach"
    bl_label = "Attach to Camera"

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "FONT"

    def execute(self, context):
        obj = context.object
        camera = context.scene.camera
        if camera is None:
            self.report({"WARNING"}, "The scene has no active camera")
            return {"CANCELLED"}
        if obj.bridge_at_attach:
            apply_camera_attach(obj, camera)
        else:
            detach_camera(obj)
        return {"FINISHED"}


class BRIDGE_OT_at_attach_attached(bpy.types.Operator):
    """Re-apply the attachment for the subtitle attached to the active camera."""
    bl_idname = "bridge.at_attach_attached"
    bl_label = "Re-apply Attachment"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "CAMERA" and attached_subtitle(obj) is not None

    def execute(self, context):
        camera = context.object
        obj = attached_subtitle(camera)
        apply_camera_attach(obj, camera)
        self.report({"INFO"}, "Subtitle attachment re-applied")
        return {"FINISHED"}


class BRIDGE_OT_at_export_srt(bpy.types.Operator):
    """Export the subtitles as an SRT file."""
    bl_idname = "bridge.at_export_srt"
    bl_label = "Export Subtitles (.srt)"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "FONT"

    def execute(self, context):
        obj = context.object
        if not get_cues(obj):
            self.report({"WARNING"}, "No subtitle cues to export")
            return {"CANCELLED"}
        render = context.scene.render
        fps = render.fps / render.fps_base if render.fps_base else render.fps
        path = self.filepath or (context.blend_data.filepath or "").rsplit(".", 1)[0] + ".srt"
        msg = export_srt(obj, path, fps, context.scene.frame_end)
        self.report({"INFO"}, msg)
        print("BRIDGE:", msg)
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class BRIDGE_OT_at_import_srt(bpy.types.Operator):
    """Import subtitles from an SRT file into cues."""
    bl_idname = "bridge.at_import_srt"
    bl_label = "Import Subtitles (.srt)"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "FONT"

    def execute(self, context):
        obj = context.object
        render = context.scene.render
        fps = render.fps / render.fps_base if render.fps_base else render.fps
        msg = import_srt(obj, self.filepath, fps)
        self.report({"INFO"}, msg)
        print("BRIDGE:", msg)
        sync_all_font_objects(context.scene)
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


# --------------------------------------------------------------------------- #
# Panel + properties + keymap
# --------------------------------------------------------------------------- #
class DATA_PT_bridge_subtitles(bpy.types.Panel):
    bl_label = "Animated Subtitles"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "FONT"

    def draw(self, context):
        layout = self.layout
        obj = context.object

        layout.prop(obj.data, "body", text="Text")

        row = layout.row(align=True)
        row.operator("bridge.at_keyframe", text="Insert Keyframe", icon="KEY_HLT")
        row.operator("bridge.at_delete", text="Delete", icon="X")
        layout.label(text="Insert a cue at the current frame; empty text = silence.")

        layout.separator()
        box = layout.box()
        box.label(text="Subtitle Layout")
        box.prop(obj, "bridge_at_scale", text="Text Scale")
        box.prop(obj, "bridge_at_wrap_pct", text="Wrap Width (%)")

        obox = layout.box()
        obox.prop(obj, "bridge_at_outline", text="Outline")
        if obj.bridge_at_outline:
            obox.prop(obj, "bridge_at_outline_width", text="Outline Width")

        layout.separator()
        box = layout.box()
        box.prop(obj, "bridge_at_attach", text="Attach to Camera")
        if obj.bridge_at_attach:
            box.prop(obj, "bridge_at_offset_x", text="Offset X")
            box.prop(obj, "bridge_at_offset_y", text="Offset Y")
            box.operator("bridge.at_attach", text="Re-apply Attachment")

        layout.separator()
        col = layout.column(align=True)
        col.operator("bridge.at_export_srt", text="Export Subtitles (.srt)")
        col.operator("bridge.at_import_srt", text="Import Subtitles (.srt)")
        if obj.get(CUE_PROP):
            layout.label(text=f"{len(get_cues(obj))} cue(s) keyed")

        # Viewport-only preview quality. TAA reprojection ghosts subtitles when
        # they appear on a cue (the viewport reuses the previous frame's samples);
        # it does NOT affect the final render. Expose the real EEVEE settings so
        # the checkbox always reflects the scene's current state.
        layout.separator()
        box = layout.box()
        box.label(text="Viewport Playback (preview only)")
        ee = context.scene.eevee
        box.prop(ee, "use_taa_reprojection", text="TAA Reprojection")
        box.prop(ee, "taa_samples", text="TAA Samples")
        box.label(text="OFF = crisp subtitles on cue; ON = less shimmer on camera move.", icon="INFO")


class DATA_PT_bridge_camera_subtitles(bpy.types.Panel):
    """Subtitle controls for the text attached to the active camera.

    Lets you edit the subtitle and add/remove cue keyframes without expanding
    the camera and selecting the text object.
    """
    bl_label = "Animated Subtitles (Camera)"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "CAMERA" and attached_subtitle(obj) is not None

    def draw(self, context):
        obj = attached_subtitle(context.object)
        layout = self.layout
        row = layout.row()
        row.label(text=f"Subtitle: {obj.name}", icon="FONT_DATA")

        layout.prop(obj.data, "body", text="Text")
        row = layout.row(align=True)
        row.operator("bridge.at_keyframe_attached", text="Insert Keyframe", icon="KEY_HLT")
        row.operator("bridge.at_delete_attached", text="Delete", icon="X")
        layout.label(text="Insert a cue at the current frame; empty text = silence.")

        layout.separator()
        box = layout.box()
        box.label(text="Subtitle Layout")
        box.prop(obj, "bridge_at_scale", text="Text Scale")
        box.prop(obj, "bridge_at_wrap_pct", text="Wrap Width (%)")

        obox = layout.box()
        obox.prop(obj, "bridge_at_outline", text="Outline")
        if obj.bridge_at_outline:
            obox.prop(obj, "bridge_at_outline_width", text="Outline Width")

        layout.separator()
        box = layout.box()
        box.label(text="Camera Attachment")
        box.prop(obj, "bridge_at_offset_x", text="Offset X")
        box.prop(obj, "bridge_at_offset_y", text="Offset Y")
        box.operator("bridge.at_attach_attached", text="Re-apply Attachment")

        if obj.get(CUE_PROP):
            layout.label(text=f"{len(get_cues(obj))} cue(s) keyed")

        layout.separator()
        box = layout.box()
        box.label(text="Viewport Playback (preview only)")
        ee = context.scene.eevee
        box.prop(ee, "use_taa_reprojection", text="TAA Reprojection")
        box.prop(ee, "taa_samples", text="TAA Samples")
        box.label(text="OFF = crisp subtitles on cue; ON = less shimmer on camera move.", icon="INFO")


def _on_attach_update(self, context):
    """Toggle handler for the camera-attach checkbox."""
    if getattr(self, "type", None) != "FONT":
        return
    if self.bridge_at_attach:
        camera = context.scene.camera
        if camera is not None:
            apply_camera_attach(self, camera)
    else:
        detach_camera(self)


def _on_layout_update(self, context):
    """Re-apply the attachment when the text scale or wrap width change."""
    if getattr(self, "type", None) != "FONT":
        return
    if self.bridge_at_attach and context.scene.camera is not None:
        apply_camera_attach(self, context.scene.camera)


def _on_outline_update(self, context):
    """Create/refresh/remove the outline when its settings change."""
    if getattr(self, "type", None) != "FONT":
        return
    apply_outline(self)


def _register_props():
    bpy.types.Object.bridge_at_attach = bpy.props.BoolProperty(
        name="Attach to Camera",
        default=False,
        description="Parent the text to the camera and place it as a subtitle",
        update=_on_attach_update,
    )
    bpy.types.Object.bridge_at_offset_x = bpy.props.FloatProperty(
        name="Offset X", default=0.0, unit="LENGTH", precision=3
    )
    bpy.types.Object.bridge_at_offset_y = bpy.props.FloatProperty(
        name="Offset Y", default=0.0, unit="LENGTH", precision=3
    )
    bpy.types.Object.bridge_at_scale = bpy.props.FloatProperty(
        name="Text Scale", default=DEFAULT_SCALE, min=0.0001, max=10.0,
        precision=3, description="Uniform scale of the subtitle text",
        update=_on_layout_update,
    )
    bpy.types.Object.bridge_at_wrap_pct = bpy.props.FloatProperty(
        name="Wrap Width", default=DEFAULT_WRAP_PCT, min=5.0, max=100.0,
        precision=1, description="Text wraps at this % of the camera frame width",
        update=_on_layout_update,
    )
    bpy.types.Object.bridge_at_outline = bpy.props.BoolProperty(
        name="Outline", default=False,
        description="Draw a contrasting outline behind the subtitle text",
        update=_on_outline_update,
    )
    bpy.types.Object.bridge_at_outline_width = bpy.props.FloatProperty(
        name="Outline Width", default=DEFAULT_OUTLINE_WIDTH, min=0.0, max=1.0,
        precision=3, description="Outline thickness (glyph offset, font units)",
        update=_on_outline_update,
    )


def _unregister_props():
    for name in (
        "bridge_at_attach", "bridge_at_offset_x", "bridge_at_offset_y",
        "bridge_at_scale", "bridge_at_wrap_pct",
        "bridge_at_outline", "bridge_at_outline_width",
    ):
        if hasattr(bpy.types.Object, name):
            delattr(bpy.types.Object, name)


_addon_keymaps = []


def _register_keymap():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if not kc:
        return
    km = kc.keymaps.get("Object Non-modal")
    if km is None:
        km = kc.keymaps.new(name="Object Non-modal", space_type="EMPTY")
    kmi = km.keymap_items.new("bridge.at_keyframe", type="I", value="PRESS")
    _addon_keymaps.append((km, kmi))


def _unregister_keymap():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:  # noqa: BLE001
            pass
    _addon_keymaps.clear()


classes = (
    BRIDGE_OT_at_keyframe,
    BRIDGE_OT_at_delete,
    BRIDGE_OT_at_keyframe_attached,
    BRIDGE_OT_at_delete_attached,
    BRIDGE_OT_at_attach,
    BRIDGE_OT_at_attach_attached,
    BRIDGE_OT_at_export_srt,
    BRIDGE_OT_at_import_srt,
    DATA_PT_bridge_subtitles,
    DATA_PT_bridge_camera_subtitles,
)


def register():
    _register_props()
    for cls in classes:
        bpy.utils.register_class(cls)
    _register_keymap()
    # frame_change_pre (not post) so the body/outline are set BEFORE the
    # depsgraph evaluates the new frame — otherwise the outline renders on top
    # with stale geometry for one frame at each keyframe / loop restart.
    if _on_frame_change not in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.append(_on_frame_change)
    if _on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    _disable_taa_for_subtitles()


def unregister():
    if _on_frame_change in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.remove(_on_frame_change)
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    _unregister_keymap()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    _unregister_props()
