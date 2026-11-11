"""Render the Grease Pencil animation to PNG sequences (for the Krita handoff).

This mirrors the manual workflow the user follows: render the scene from the
camera as a PNG image sequence with a transparent film, then import that
sequence into Krita as animation frames.

``render_layers_to_pngs`` renders **each Grease Pencil layer in isolation** so
Krita can reconstruct the drawing as separate paint layers (one per GP layer),
preserving layer names and stacking order.
"""

from __future__ import annotations

import os

import bpy

from . import gp_layer_autokey


def _safe_filename(name: str) -> str:
    """Turn a GP layer name into a filesystem-safe directory name."""
    keep = "".join(c if (c.isalnum() or c in "-_ ") else "_" for c in name)
    keep = keep.replace(" ", "_").strip("_")
    return keep or "layer"


def _prepare_render(context):
    """Force EEVEE + transparent film; return saved state for restore."""
    scene = context.scene
    render = scene.render
    view = scene.view_settings
    saved = {
        "engine": render.engine,
        "filepath": render.filepath,
        "film_transparent": render.film_transparent,
        "file_format": render.image_settings.file_format,
        "view_transform": view.view_transform,
    }
    # EEVEE renders GP strokes + transparent film correctly (other engines
    # render GP as opaque black / ignore film_transparent).
    render.engine = "BLENDER_EEVEE"
    render.film_transparent = True
    render.image_settings.file_format = "PNG"
    view.view_transform = "Standard"
    return saved


def _restore_render(context, saved):
    render = context.scene.render
    view = context.scene.view_settings
    render.engine = saved["engine"]
    render.filepath = saved["filepath"]
    render.film_transparent = saved["film_transparent"]
    render.image_settings.file_format = saved["file_format"]
    view.view_transform = saved["view_transform"]


def _layer_content_frames(layer, start: int, end: int) -> list:
    """Frame numbers in [start, end] whose drawing actually has strokes.

    Only frames with at least one stroke are rendered — keyframes with an empty
    drawing (or no keyframe at all) produce a fully transparent frame and are
    skipped, so a drawing made on frame 1 renders one frame instead of the
    whole ``start..end`` range (Blender's default is 1..250).
    """
    out = []
    for frame in layer.frames:
        fn = frame.frame_number
        if fn < start or fn > end:
            continue
        drawing = frame.drawing
        if drawing is not None and len(drawing.strokes) > 0:
            out.append(fn)
    return sorted(out)


# --------------------------------------------------------------------------- #
# Layer-transform capture (preserved on the returned image planes)
# --------------------------------------------------------------------------- #

def _transform_fcurves(gpd, layer_name: str) -> list:
    """Return ``(fcurve, prop, axis)`` for a layer's transform fcurves.

    Layer transforms are keyed as ``layers["<name>"].translation`` /
    ``.rotation`` / ``.scale`` (array_index 0/1/2) in the layered action.
    """
    prefix = f'layers["{layer_name}"].'
    out = []
    ad = gpd.animation_data
    if not ad or not ad.action:
        return out
    for action_layer in ad.action.layers:
        for strip in action_layer.strips:
            if strip.type != "KEYFRAME":
                continue
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    if not fc.data_path.startswith(prefix):
                        continue
                    prop = fc.data_path[len(prefix):]
                    if prop in ("translation", "rotation", "scale"):
                        out.append((fc, prop, fc.array_index))
    return out


def _eval_layer_transform(gpd, layer_name: str, frame: int) -> dict:
    """Evaluate a layer's translation/rotation/scale at ``frame`` (fcurves)."""
    layer = gpd.layers[layer_name]
    props = {
        "translation": [float(layer.translation[i]) for i in range(3)],
        "rotation": [float(layer.rotation[i]) for i in range(3)],
        "scale": [float(layer.scale[i]) for i in range(3)],
    }
    for fc, prop, axis in _transform_fcurves(gpd, layer_name):
        props[prop][axis] = float(fc.evaluate(frame))
    return props


def _capture_layer_transform(gpd, layer) -> dict:
    """Capture a layer's transform + its keyframes (for the return path)."""
    info = {
        "translation": [float(layer.translation[i]) for i in range(3)],
        "rotation": [float(layer.rotation[i]) for i in range(3)],
        "scale": [float(layer.scale[i]) for i in range(3)],
        "keyframes": [],
    }
    frames = set()
    for fc, _prop, _axis in _transform_fcurves(gpd, layer.name):
        for kp in fc.keyframe_points:
            frames.add(int(kp.co[0]))
    for f in sorted(frames):
        p = _eval_layer_transform(gpd, layer.name, f)
        info["keyframes"].append(
            {
                "frame": f,
                "translation": p["translation"],
                "rotation": p["rotation"],
                "scale": p["scale"],
            }
        )
    return info


def _identity_layer_transform(layer):
    layer.translation = (0.0, 0.0, 0.0)
    layer.rotation = (0.0, 0.0, 0.0)
    layer.scale = (1.0, 1.0, 1.0)


def _restore_layer_transform(layer, translation, rotation, scale):
    layer.translation = translation
    layer.rotation = rotation
    layer.scale = scale


def render_animation_to_pngs(context, out_dir: str) -> dict:
    """Render scene.frame_start..frame_end to PNGs; return metadata dict."""
    scene = context.scene
    if scene.camera is None:
        raise RuntimeError("The scene has no active camera — add one first")

    saved = _prepare_render(context)
    render = scene.render
    render.filepath = os.path.join(out_dir, "frame_####.png")
    os.makedirs(out_dir, exist_ok=True)

    try:
        print(f"Bridge: rendering frames {scene.frame_start}..{scene.frame_end}...")
        bpy.ops.render.render(animation=True)
        print("Bridge: render done")
    finally:
        _restore_render(context, saved)

    start, end = scene.frame_start, scene.frame_end
    files = [os.path.join(out_dir, f"frame_{i:04d}.png") for i in range(start, end + 1)]
    fps = render.fps / render.fps_base if render.fps_base else render.fps
    return {
        "files": files,
        "frame_start": start,
        "frame_end": end,
        "fps": fps,
    }


def render_layers_to_pngs(context, obj, out_dir: str) -> dict:
    """Render each Grease Pencil layer of `obj` in isolation, backmost first.

    Returns::

        {"width": int, "height": int, "fps": float,
         "frame_start": int, "frame_end": int,
         "layers": [{"name": str, "frame_start": int,
                     "files": [str, ...]}, ...]}

    ``layers`` is ordered back-to-front (Blender ``gpd.layers`` index order:
    ``layers[0]`` is drawn first/behind, the last layer is drawn last/front).
    Krita's ``importAnimation`` stacks each imported layer on top of the
    previous, so importing in this order reproduces the Blender stacking.

    Only the frames that actually contain strokes are rendered — the scene's
    full ``frame_start..frame_end`` range (Blender default 1..250) is NOT
    rendered, which is what caused slow exports and multi-GB Krita documents.
    """
    scene = context.scene
    if scene.camera is None:
        raise RuntimeError("The scene has no active camera — add one first")

    gpd = obj.data
    render = scene.render
    saved = _prepare_render(context)

    # Remember per-layer visibility, other-object render visibility and the
    # scene frame range so we can restore everything afterwards.
    layer_states = [(layer, layer.hide) for layer in gpd.layers]
    other_objects = [o for o in scene.objects if o is not obj and not o.hide_render]
    scene_start, scene_end = scene.frame_start, scene.frame_end
    scene_frame_current = scene.frame_current
    fps = render.fps / render.fps_base if render.fps_base else render.fps

    # Pre-compute, per layer, the frame numbers that actually contain strokes.
    layer_content_frames = {
        layer.name: _layer_content_frames(layer, scene_start, scene_end)
        for layer in gpd.layers
    }

    layers_out = []
    # The isolated render temporarily zeroes each layer's transform; suspend the
    # auto-key handler so those temporary edits don't write spurious keyframes
    # into the layer (they used to appear at the last rendered frame).
    gp_layer_autokey.suspend()
    try:
        # Only the GP drawing should reach Krita: hide every other object.
        for o in other_objects:
            o.hide_render = True

        os.makedirs(out_dir, exist_ok=True)
        for layer in gpd.layers:
            # Isolate this layer.
            for L, _ in layer_states:
                L.hide = True
            layer.hide = False

            # Capture the layer transform so the returned image plane can be
            # placed where the layer was. The isolated render runs with the
            # transform zeroed (and its fcurves muted) so the transform is NOT
            # baked into the PNG — it's applied to the plane on return instead.
            transform_info = _capture_layer_transform(gpd, layer)
            transform_fcurves = _transform_fcurves(gpd, layer.name)
            saved_transform = (
                tuple(layer.translation),
                tuple(layer.rotation),
                tuple(layer.scale),
            )
            for fc, _prop, _axis in transform_fcurves:
                fc.mute = True
            _identity_layer_transform(layer)

            try:
                frames = layer_content_frames[layer.name]
                if not frames:
                    layers_out.append(
                        {
                            "name": layer.name,
                            "files": [],
                            "frame_start": scene_start,
                            "transform": transform_info,
                        }
                    )
                    continue

                layer_dir = os.path.join(out_dir, _safe_filename(layer.name))
                os.makedirs(layer_dir, exist_ok=True)

                # Render the continuous span [first, last]. Frames without strokes
                # come out as holds of the previous drawing; Krita imports them all
                # and then deletes the non-active ones using `active_frames`, so
                # only the real keyframes remain (irregular gaps included).
                l_start, l_end = frames[0], frames[-1]
                render.filepath = os.path.join(layer_dir, "frame_####.png")
                print(
                    f"Bridge: layer '{layer.name}' rendering span {l_start}..{l_end} "
                    f"(active frames: {frames})"
                )
                scene.frame_start, scene.frame_end = l_start, l_end
                bpy.ops.render.render(animation=True)

                files = [
                    os.path.join(layer_dir, f"frame_{i:04d}.png")
                    for i in range(l_start, l_end + 1)
                ]
                layers_out.append(
                    {
                        "name": layer.name,
                        "files": files,
                        "frame_start": l_start,
                        "active_frames": frames,
                        "transform": transform_info,
                    }
                )
            finally:
                _restore_layer_transform(layer, *saved_transform)
                for fc, _prop, _axis in transform_fcurves:
                    fc.mute = False
    finally:
        _restore_render(context, saved)
        scene.frame_start, scene.frame_end = scene_start, scene_end
        scene.frame_current = scene_frame_current
        for layer, hide in layer_states:
            layer.hide = hide
        for o in other_objects:
            o.hide_render = False
        gp_layer_autokey.resume()

    return {
        "width": render.resolution_x,
        "height": render.resolution_y,
        "fps": fps,
        "frame_start": scene_start,
        "frame_end": scene_end,
        "layers": layers_out,
    }



