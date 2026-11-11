"""Apply a Krita -> Blender import-back message to the original object."""

from __future__ import annotations

import os
import tempfile

import bpy

from . import image_import


def find_object_by_uuid(object_uuid):
    for obj in bpy.data.objects:
        if obj.get("object_uuid") == object_uuid:
            return obj
    return None


def _get_or_create_collection(name):
    """Return the named collection, creating + linking it to the scene if new."""
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
    return collection


def _find_existing_plane(collection_name, plane_name):
    """Return a plane with ``plane_name`` in ``collection_name``, or None."""
    if not collection_name:
        return None
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        return None
    for obj in collection.objects:
        if obj.name == plane_name:
            return obj
    return None


def _layer_transform(obj, layer_name):
    """Look up the captured GP layer transform (stored at export time)."""
    for entry in obj.get("bridge_layer_transforms", []):
        if entry.get("name") == layer_name:
            return entry.get("transform")
    return None


def _warm_up_eevee():
    """Force EEVEE to compile + upload every keyframe texture of every plane.

    The animated image planes mix one texture per keyframe via driver-driven Mix
    nodes. EEVEE only uploads a texture the first time it is actually sampled,
    so the first pass over the timeline (and every loop if the viewport texture
    pool evicts it) hitches once per keyframe. A tiny render at every keyframe
    frame pre-samples every texture so playback no longer stalls per keyframe.
    """
    scene = bpy.context.scene
    if scene is None or scene.camera is None:
        return
    render = scene.render
    saved = (
        render.engine,
        render.resolution_x,
        render.resolution_y,
        render.use_border,
        render.border_min_x,
        render.border_min_y,
        render.border_max_x,
        render.border_max_y,
    )
    saved_frame = scene.frame_current
    try:
        render.engine = "BLENDER_EEVEE"
        render.resolution_x = 16
        render.resolution_y = 16
        render.use_border = False

        # Animated image planes (objects with a keyframed `bridge_frame`).
        keyframes = set()
        for obj in scene.objects:
            frames = obj.get("bridge_frames")
            if frames is not None:
                for f in frames:
                    keyframes.add(int(f))
        if not keyframes:
            bpy.ops.render.render()  # in-memory; fills the Render Result, no file
            return

        # Render once at every keyframe frame: at each frame the CONSTANT
        # `bridge_frame` selects a different texture, so every texture gets
        # sampled (and therefore uploaded/compiled) before playback.
        for f in sorted(keyframes):
            scene.frame_set(f)
            bpy.ops.render.render()
    except Exception as exc:  # noqa: BLE001
        print("BRIDGE: warm-up render failed:", exc)
    finally:
        try:
            scene.frame_set(saved_frame)
        except Exception:  # noqa: BLE001
            pass
        (
            render.engine,
            render.resolution_x,
            render.resolution_y,
            render.use_border,
            render.border_min_x,
            render.border_min_y,
            render.border_max_x,
            render.border_max_y,
        ) = saved


def apply_import_back(msg) -> str:
    """Create camera-aligned image planes from the returned PNG layers.

    Each Krita paint layer becomes one renderable plane, stacked front-to-back
    over the GP outline (which stays intact as the sketch reference). Animated
    layers (multiple keyframes) become image sequences that play with holds;
    static layers become single-image planes. The plane goes into the collection
    matching its Krita group: layers inside the imported group (named after the
    GP object) land in the object's collection, layers inside any other group
    get that group's own collection, and loose layers (not inside any group) go
    to a "Krita" collection.

    If a plane with the same name already exists in that collection (an
    image-plane round-trip), its texture is REPLACED in place — the object's
    transform/modifiers (parallax, rotation keyframes) are preserved.
    """
    object_uuid = msg.get("object_uuid")
    obj = find_object_by_uuid(object_uuid)
    if obj is None:
        return f"object_uuid not found: {object_uuid}"

    layers = msg.get("layers", [])
    height = image_import.camera_view_rect(bpy.context.scene, obj)[4]
    epsilon = height * 1e-4  # tiny per-layer offset to avoid z-fighting

    # The animation's global end frame = the latest keyframe across all layers
    # (or the document's clip-range end if it extends further). Animated layers
    # hold from their last keyframe up to this frame.
    global_end = int(msg.get("frame_end", 0) or 0)
    for layer_info in layers:
        for fr in layer_info.get("frames", []):
            try:
                global_end = max(global_end, int(fr.get("frame", 1)))
            except (TypeError, ValueError):
                pass

    out_root = os.path.join(tempfile.gettempdir(), "BlenderKritaBridge", "back", object_uuid)

    created = 0
    replaced = 0
    for index, layer_info in enumerate(layers):
        name = layer_info.get("name") or f"Krita Layer {index + 1}"
        group = layer_info.get("group")
        collection = _get_or_create_collection(group or "Krita")

        frames = layer_info.get("frames") or []
        # Backward-compat: older messages carried a single top-level `file`.
        if not frames and layer_info.get("file"):
            frames = [{"frame": layer_info.get("frame_number", 1), "file": layer_info["file"]}]
        if not frames:
            continue

        # Image-plane round-trip: replace the existing plane's texture in place.
        existing = _find_existing_plane(group, name)
        if existing is not None:
            image_import.update_plane_textures(existing, frames)
            replaced += 1
            continue

        transform = _layer_transform(obj, name)
        if len(frames) <= 1:
            path = frames[0].get("file")
            if not path:
                continue
            plane = image_import.create_image_plane(
                bpy.context.scene, path, obj, name,
                z_offset=index * epsilon, collection=collection,
            )
            if transform:
                image_import.apply_layer_transform(plane, obj, transform)
        else:
            seq_dir = os.path.join(out_root, f"seq_{index:02d}")
            plane = image_import.create_image_plane_sequence(
                bpy.context.scene, frames, global_end, seq_dir, obj, name,
                z_offset=index * epsilon, collection=collection,
            )
            if plane is not None and transform:
                image_import.apply_layer_transform(plane, obj, transform)
        created += 1

    _warm_up_eevee()

    if replaced:
        return f"replaced {replaced} texture(s), created {created} plane(s) aligned to {obj.name}"
    return f"created {created} image plane(s) aligned to {obj.name}"
