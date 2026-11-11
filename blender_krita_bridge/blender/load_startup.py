"""Load the bundled Blender startup scene + workspace as a fresh working copy.

The plugin ships a ``startup.blend`` (a copy of the author's Blender startup —
the "Storyboarding" screen layout plus the animation-asset scenes). Loading it
must NOT open the bundled file directly: a plain "Save" would then overwrite
the shipped default and lose the blank template.

We copy the bundle to a fresh writable file in Blender's temp dir and open THAT
copy with ``open_mainfile`` — a normal file open, so Blender's preferences and
addons are left untouched, and the bundled ``assets/startup.blend`` is never
written to.
"""

from __future__ import annotations

import os
import shutil
import time

import bpy

def startup_blend_path() -> str | None:
    """Absolute path of the bundled startup file, or ``None`` when missing."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.normpath(os.path.join(here, "..", "assets", "startup.blend"))
    return path if os.path.isfile(path) else None


def _working_copy_path() -> str:
    """Fresh writable scratch path for the copy (Save never touches the bundle)."""
    out_dir = os.path.join(bpy.app.tempdir, "StoryPaint")
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(out_dir, "StoryPaint_{}.blend".format(stamp))


def _prune_old_copies(keep: int = 2) -> None:
    """Delete older scratch copies, keeping only the ``keep`` most recent.

    Each load drops a fresh copy in Blender's temp dir; without pruning these
    would accumulate forever. The user's unsaved work lives in at most the two
    newest copies — anything older is removed.
    """
    out_dir = os.path.join(bpy.app.tempdir, "StoryPaint")
    if not os.path.isdir(out_dir):
        return
    files = sorted(
        (
            os.path.join(out_dir, name)
            for name in os.listdir(out_dir)
            if name.startswith("StoryPaint_") and name.endswith(".blend")
        ),
        key=os.path.getmtime,
    )
    for path in files[:-keep]:
        try:
            os.remove(path)
        except OSError:
            pass


def _focus_storypaint_panel():
    """Make the StoryPaint sidebar tab active in every 3D viewport.

    Runs on a one-shot timer after the file loads: the sidebar's active tab is
    part of the loaded screen layout, so this sets it to our own tab instead of
    leaving whatever other plugin was expanded.
    """
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type != "VIEW_3D":
                    continue
                for region in area.regions:
                    if region.type == "UI":
                        try:
                            region.active_panel_category = "StoryPaint"
                        except (AttributeError, TypeError):
                            pass
    except Exception:  # noqa: BLE001
        pass
    return None  # one-shot


class BRIDGE_OT_load_startup(bpy.types.Operator):
    """Open the bundled startup as a new working copy (never overwrites the default)."""
    bl_idname = "bridge.load_startup"
    bl_label = "Load Blender Startup Workspace"
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        # Loading discards the current (possibly unsaved) session, so ask first.
        return context.window_manager.invoke_props_dialog(self, width=440)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Load the bundled startup scene and workspace?")
        layout.label(text="Unsaved changes in the current file will be lost.", icon="ERROR")
        layout.label(
            text="It opens a working copy — use Save As to keep it as your project.",
            icon="INFO",
        )

    def execute(self, context):
        path = startup_blend_path()
        if path is None:
            self.report({"ERROR"}, "Bundled startup file not found")
            return {"CANCELLED"}
        try:
            copy_path = _working_copy_path()
            shutil.copy2(path, copy_path)
        except OSError as exc:
            self.report({"ERROR"}, "Could not copy the startup file: {}".format(exc))
            return {"CANCELLED"}
        _prune_old_copies()
        bpy.ops.wm.open_mainfile(filepath=copy_path)
        # After the load settles, make our own tab active so no other plugin's
        # panel is left expanded over the user's workspace.
        bpy.app.timers.register(_focus_storypaint_panel, first_interval=0.2)
        return {"FINISHED"}


classes = (BRIDGE_OT_load_startup,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
