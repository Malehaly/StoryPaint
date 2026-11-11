"""Export operator: active Grease Pencil object -> Krita (camera-rendered PNGs)."""

from __future__ import annotations

import os
import tempfile

import bpy

from ..common import ids
from ..core import protocol
from . import connection, render_export


def _ensure_uuid(obj) -> str:
    value = obj.get("object_uuid")
    if not value:
        value = ids.new_uuid()
        obj["object_uuid"] = value
    return value


class BRIDGE_OT_export_package(bpy.types.Operator):
    bl_idname = "bridge.export_package"
    bl_label = "Export GP to Krita"
    bl_description = (
        "Render the Grease Pencil object's layers from the scene camera "
        "and send them to Krita as paintable layers"
    )

    object_name: bpy.props.StringProperty(name="Object", default="", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is not None and obj.type == "GREASEPENCIL":
            return True
        # Outliner context menu: context.id is the object under the cursor.
        id_ = getattr(context, "id", None)
        return isinstance(id_, bpy.types.Object) and id_.type == "GREASEPENCIL"

    def execute(self, context):
        obj = bpy.data.objects.get(self.object_name) if self.object_name else context.object
        if obj is None or obj.type != "GREASEPENCIL":
            self.report({"WARNING"}, "Select a Grease Pencil object first")
            return {"CANCELLED"}
        scene = context.scene

        object_uuid = _ensure_uuid(obj)

        out_dir = os.path.join(tempfile.gettempdir(), "BlenderKritaBridge", object_uuid)
        print(f"Bridge: output dir = {out_dir}")
        try:
            result = render_export.render_layers_to_pngs(context, obj, out_dir)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        n_layers = len(result["layers"])
        n_files = sum(len(l["files"]) for l in result["layers"])
        print(f"Bridge: rendered {n_files} frame(s) across {n_layers} layer(s), sending to Krita...")
        # Remember each layer's transform so the return path can place the image
        # planes where the GP layers were (the render is done with transforms
        # zeroed, so this metadata is the only record of the position).
        obj["bridge_layer_transforms"] = [
            {"name": l["name"], "transform": l.get("transform")}
            for l in result["layers"]
        ]
        server = connection.BridgeServer.instance()
        server.start()
        message = {
            "type": protocol.MSG_EXPORT,
            "object_uuid": object_uuid,
            "object_name": obj.name,
            "scene_name": scene.name,
            "width": result["width"],
            "height": result["height"],
            "fps": result["fps"],
            "frame_start": result["frame_start"],
            "layers": result["layers"],
        }
        if server.send(message):
            self.report({"INFO"}, f"Sent {n_layers} layer(s) to Krita")
            print(f"Bridge: sent {n_layers} layer(s) to Krita")
        else:
            self.report(
                {"WARNING"},
                "Krita not connected — enable the StoryPaint plugin there",
            )
            print("Bridge: Krita not connected")
        return {"FINISHED"}


classes = (BRIDGE_OT_export_package,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
