"""Export the bridge image planes back to Krita (re-edit the painted art).

The bridge turns Krita paint layers into camera-aligned image planes (one mesh
per layer, with a mix-shader material carrying one texture per keyframe). This
operator reverses that: it reads each plane's textures + keyframe order and
sends them back to Krita as paintable layers, so the art can be edited again
even after the original Grease Pencil reference was deleted.
"""

from __future__ import annotations

import os
import tempfile

import bpy

from ..common import ids
from ..core import protocol
from . import connection, image_import


def _is_bridge_plane(obj):
    if obj.type != "MESH" or not obj.data or not obj.data.materials:
        return False
    mat = obj.data.materials[0]
    if not mat.use_nodes:
        return False
    return any(n.type == "TEX_IMAGE" for n in mat.node_tree.nodes)


def _plane_keyframes(obj):
    """Return sorted ``[(frame, image)]`` for a bridge plane, or None."""
    mat = obj.data.materials[0]
    tex_nodes = [n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE"]
    if not tex_nodes:
        return None
    if "bridge_frame" in obj:
        kf = []
        for frame, value in image_import._bridge_frame_points(obj):
            img = next(
                (n.image for n in tex_nodes if n.get("bridge_index") == value),
                None,
            )
            if img is not None:
                kf.append((frame, img))
        return kf or None
    # Static single-texture plane.
    if tex_nodes[0].image is not None:
        return [(1, tex_nodes[0].image)]
    return None


def _save_image_copy(img, path):
    """Save the image's current pixels to ``path`` as a PNG.

    The bridge images are loaded from disk, so ``Image.copy()`` would produce a
    copy without pixel data. Read the pixels (forces a load) and write them to a
    fresh image instead.
    """
    w, h = img.size
    pixels = img.pixels[:]
    new = bpy.data.images.new("bridge_export_tmp", w, h, alpha=True)
    new.pixels = pixels
    new.filepath_raw = path
    new.file_format = "PNG"
    new.save()
    bpy.data.images.remove(new)
    return path


def _ensure_uuid(obj) -> str:
    value = obj.get("object_uuid")
    if not value:
        value = ids.new_uuid()
        obj["object_uuid"] = value
    return value


def _collection_name(obj) -> str:
    cols = obj.users_collection
    return cols[0].name if cols else "Krita"


def _texture_resolution(obj):
    """Return (w, h) of the plane's first texture, or None."""
    if not obj.data or not obj.data.materials:
        return None
    mat = obj.data.materials[0]
    if not mat.use_nodes:
        return None
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image is not None:
            return n.image.size[0], n.image.size[1]
    return None


class BRIDGE_OT_export_image_planes(bpy.types.Operator):
    bl_idname = "bridge.export_image_planes"
    bl_label = "Export Image Planes to Krita"
    bl_description = (
        "Send the selected image planes' textures (with their keyframe order) "
        "back to Krita as paintable layers"
    )

    object_name: bpy.props.StringProperty(name="Object", default="", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        if any(_is_bridge_plane(o) for o in context.selected_objects):
            return True
        # Outliner context menu: context.id is the object under the cursor.
        id_ = getattr(context, "id", None)
        return isinstance(id_, bpy.types.Object) and _is_bridge_plane(id_)

    def execute(self, context):
        if self.object_name:
            obj = bpy.data.objects.get(self.object_name)
            planes = [obj] if (obj is not None and _is_bridge_plane(obj)) else []
        else:
            planes = [o for o in context.selected_objects if _is_bridge_plane(o)]
        if not planes:
            self.report({"WARNING"}, "Select one or more image planes first")
            return {"CANCELLED"}

        scene = context.scene
        object_uuid = _ensure_uuid(planes[0])
        out_root = os.path.join(tempfile.gettempdir(), "BlenderKritaBridge", "planes")
        os.makedirs(out_root, exist_ok=True)

        # The Krita canvas = the texture's NATURAL resolution (not the camera's),
        # so images from other programs keep their own size and the plane's
        # transform stays valid when the texture is replaced in place.
        res = _texture_resolution(planes[0])
        width, height = res if res else (scene.render.resolution_x, scene.render.resolution_y)

        layers = []
        for idx, obj in enumerate(planes):
            kf = _plane_keyframes(obj)
            if not kf:
                continue
            kf.sort()
            # Save each keyframe image, then build a contiguous span with holds
            # so Krita can import it and delete the non-active frames (this is
            # the same flow the Grease Pencil export uses).
            kf_dir = os.path.join(out_root, f"layer_{idx:02d}")
            os.makedirs(kf_dir, exist_ok=True)
            kf_files = []
            for frame, img in kf:
                path = _save_image_copy(
                    img, os.path.join(kf_dir, f"kf_{frame:04d}.png")
                )
                kf_files.append({"frame": frame, "file": path})
            end_frame = max(f for f, _ in kf)
            seq_dir = os.path.join(out_root, f"seq_{idx:02d}")
            _, count, first_frame, _ = image_import.build_sequence_files(
                kf_files, end_frame, seq_dir
            )
            files = [
                os.path.join(seq_dir, f"frame_{i:04d}.png")
                for i in range(1, count + 1)
            ]
            layers.append(
                {
                    "name": obj.name,
                    "group": _collection_name(obj),
                    "files": files,
                    "frame_start": first_frame,
                    "active_frames": [f for f, _ in kf],
                }
            )

        if not layers:
            self.report({"WARNING"}, "No image planes with textures found")
            return {"CANCELLED"}

        server = connection.BridgeServer.instance()
        server.start()
        message = {
            "type": protocol.MSG_EXPORT,
            "object_uuid": object_uuid,
            "object_name": planes[0].name,
            "scene_name": scene.name,
            "width": width,
            "height": height,
            "fps": scene.render.fps,
            "frame_start": layers[0]["frame_start"],
            "layers": layers,
        }
        if server.send(message):
            self.report({"INFO"}, f"Sent {len(layers)} layer(s) to Krita")
            print(f"Bridge: sent {len(layers)} image-plane layer(s) to Krita")
        else:
            self.report(
                {"WARNING"},
                "Krita not connected — enable the StoryPaint plugin there",
            )
            print("Bridge: Krita not connected")
        return {"FINISHED"}


classes = (BRIDGE_OT_export_image_planes,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
