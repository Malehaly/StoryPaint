"""Glue: client lifecycle + Qt timer + document import/export (Krita side)."""

from __future__ import annotations

import os
import tempfile
import time

from PyQt5.QtCore import QCoreApplication, Qt, QTimer
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QProgressDialog

from krita import Krita

from .connection import BridgeClient, MSG_EXPORT, MSG_IMPORT_BACK

client = BridgeClient()
_timer = None
_current_object_uuid = None
_doc_meta = None
last_status = "Waiting for Blender…"


def _log(event: str, detail: str = ""):
    """Append a line to the bridge log (for debugging silent failures/crashes)."""
    try:
        d = os.path.join(tempfile.gettempdir(), "BlenderKritaBridge")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "krita_bridge.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {event}: {detail}\n")
    except OSError:
        pass


def set_status(text: str):
    global last_status
    last_status = text


def start():
    client.start()
    global _timer
    if _timer is None:
        _timer = QTimer()
        _timer.timeout.connect(_poll)
        _timer.start(200)


def _poll():
    if not client.connected:
        set_status("Waiting for Blender…")
    else:
        set_status("Connected to Blender")
    for msg in client.drain_inbox():
        _handle(msg)


def _handle(msg):
    mtype = msg.get("type")
    if mtype == MSG_EXPORT:
        _apply_export(msg)


def _flush_events(seconds: float = 2.0):
    """Spin the Qt event loop briefly so Krita's async node operations complete."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def _group_layers(doc, root, group_name):
    """Wrap the imported paint layers in a passthrough group named ``group_name``.

    libkis has no move-node API, but Krita's "quick group" action performs the
    move. It groups the SELECTED layers and always leaves the ACTIVE node out,
    so we first make a temp group the active node, select all, quick-group, then
    delete the temp group and rename the result.
    """
    paint = [n for n in root.childNodes() if n.type() == "paintlayer"]
    if len(paint) <= 1:
        return  # nothing meaningful to group

    temp = doc.createNode("_bridge_temp", "grouplayer")
    root.addChildNode(temp, None)
    doc.setActiveNode(temp)

    app = Krita.instance()
    app.action("select_all_layers").trigger()
    app.action("create_quick_group").trigger()
    _flush_events(2.0)

    # Find the new group (a grouplayer that isn't our temp group).
    new_group = None
    for n in root.childNodes():
        if n.type() == "grouplayer" and n.name() != "_bridge_temp":
            new_group = n
    if new_group is None:
        return

    def _remove_named(node, name):
        for c in list(node.childNodes()):
            if c.name() == name:
                try:
                    c.remove()
                except Exception:  # noqa: BLE001
                    pass
                return
            _remove_named(c, name)

    _remove_named(root, "_bridge_temp")
    new_group.setName(group_name)
    try:
        new_group.setBlendingMode("pass-through")
    except Exception:  # noqa: BLE001
        pass


def _delete_inactive_keyframes(doc, node, active_frames, frame_start, file_count):
    """Delete imported keyframes that aren't real Blender content frames.

    The Blender side renders the continuous span and marks the frames that
    actually had strokes in ``active_frames``. ``importAnimation`` turns every
    rendered frame into a keyframe, so frames without strokes become duplicate
    "hold" keyframes — delete those so Krita holds the previous drawing
    implicitly instead (irregular keyframe gaps stay correct).
    """
    if not active_frames:
        return
    active = {int(f) for f in active_frames}
    end = int(frame_start) + int(file_count)  # exclusive
    to_delete = [
        t
        for t in range(int(frame_start), end)
        if t not in active and node.hasKeyframeAtTime(t)
    ]
    if not to_delete:
        return
    app = Krita.instance()
    doc.setActiveNode(node)
    _flush_events(0.3)
    for t in to_delete:
        doc.setCurrentTime(t)
        app.action("remove_frames").trigger()
        _flush_events(0.4)
    doc.refreshProjection()


def _apply_export(msg):
    """Create a NEW Krita document with one paint layer per Blender GP layer.

    ``msg["layers"]`` arrives back-to-front (Blender ``gpd.layers`` order).
    ``importAnimation`` stacks each imported sequence on top of the previous
    one, so importing in that same order reproduces the Blender stacking.
    """
    global _current_object_uuid
    app = Krita.instance()
    try:
        layers = msg.get("layers") or []
        # Backward-compat: older Blender addons sent a single top-level `files`
        # list instead of a per-layer `layers` list.
        if not layers and msg.get("files"):
            layers = [{"name": msg.get("object_name") or "Layer", "files": msg["files"]}]
        width = msg.get("width") or 1000
        height = msg.get("height") or 1000
        title = msg.get("scene_name") or msg.get("object_name") or "StoryPaint"
        fps = msg.get("fps") or 24
        frame_start = msg.get("frame_start", 1)

        doc = app.createDocument(width, height, title, "RGBA", "U8", "", 300.0)
        win = app.activeWindow()
        if win is None:
            win = app.openWindow()
        win.addView(doc)  # without a view the document never shows up
        app.setActiveDocument(doc)
        _current_object_uuid = msg.get("object_uuid")

        root = doc.rootNode()
        # Drop the default "Background" layer so only the GP layers remain.
        for node in list(root.childNodes()):
            node.remove()

        imported = 0
        first_content_frame = frame_start
        total = max(1, len(layers))
        progress = QProgressDialog("Preparing document…", None, 0, total)
        progress.setWindowTitle("StoryPaint — Importing")
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setCancelButton(None)
        progress.setValue(0)
        progress.show()
        try:
            for layer in layers:
                name = layer.get("name") or f"Layer {imported + 1}"
                progress.setLabelText(f"Importing layer {imported + 1}/{total}: {name}…")
                progress.setValue(imported)
                QCoreApplication.processEvents()
                files = layer.get("files") or []
                # Each layer may start at a different frame (only frames with
                # strokes are rendered on the Blender side).
                layer_start = layer.get("frame_start", frame_start)
                if files:
                    if imported == 0:
                        first_content_frame = layer_start
                    before = {n.uniqueId() for n in root.childNodes()}
                    ok = doc.importAnimation(files, layer_start, 1)
                    if not ok:
                        set_status("importAnimation returned False")
                        continue
                    new_node = next(
                        n for n in root.childNodes() if n.uniqueId() not in before
                    )
                    new_node.setName(name)
                    # Delete the hold keyframes the import created for frames
                    # that had no strokes in Blender (irregular gaps correct).
                    _delete_inactive_keyframes(
                        doc, new_node, layer.get("active_frames"), layer_start, len(files)
                    )
                else:
                    node = doc.createNode(name, "paintlayer")
                    root.addChildNode(node, None)
                imported += 1

            # Wrap the imported layers in a passthrough group named after the object.
            progress.setLabelText("Grouping layers…")
            progress.setValue(total)
            QCoreApplication.processEvents()
            _group_layers(doc, root, msg.get("object_name") or "GreasePencil")
        finally:
            progress.close()

        doc.setFramesPerSecond(int(round(fps)))
        doc.setCurrentTime(first_content_frame)  # make the first drawn frame visible
        doc.refreshProjection()
        set_status(f"Imported {imported} layer(s) from Blender")

        global _doc_meta
        _doc_meta = {
            "object_uuid": msg.get("object_uuid"),
            "width": width,
            "height": height,
            "fps": fps,
            "frame_start": frame_start,
            "layers": [
                {
                    "name": L.get("name"),
                    "group": L.get("group"),
                    "frame_start": L.get("frame_start", frame_start),
                }
                for L in layers
            ],
        }
    except Exception as exc:  # noqa: BLE001
        set_status(f"Error: {exc}")
        print("BRIDGE error:", exc)


def send_back() -> bool:
    """Send the active document's paint layers back to Blender as PNGs.

    Each paint layer becomes one or more transparent PNGs: static layers send a
    single image; animated layers send one PNG per KEYFRAME (only the frames
    where new content was drawn — no static hold frames). Blender turns each
    into a camera-aligned image plane (one plane per layer) and plays the
    keyframes back with holds, so the painting lands exactly over the GP
    outline and keeps its stacking order + animation timing.
    """
    global _doc_meta
    app = Krita.instance()
    doc = app.activeDocument()
    if doc is None:
        set_status("No document to send")
        return False
    if not _current_object_uuid:
        set_status("No Blender object linked")
        return False

    width, height = doc.width(), doc.height()
    time = doc.currentTime()

    out_dir = os.path.join(
        tempfile.gettempdir(), "BlenderKritaBridge", "back", _current_object_uuid
    )
    os.makedirs(out_dir, exist_ok=True)

    try:
        layers = []
        # Collect paint layers (they may be nested inside groups). childNodes()
        # is bottom-to-top; reverse so the message is front-to-back (Blender
        # stacks them in this order, front layer closest to the camera). Each
        # entry carries the OUTERMOST group the layer sits in (None for loose,
        # ungrouped layers) so Blender can map each group to its own collection.
        def _collect_paint(out, node, group=None):
            for c in node.childNodes():
                if c.type() == "paintlayer":
                    out.append((c, group))
                elif c.type() == "grouplayer":
                    _collect_paint(out, c, group if group is not None else c.name())

        nodes = []
        _collect_paint(nodes, doc.rootNode())
        expected = width * height * 4
        _log("send_back", f"doc={doc.name()} t={time} layers={len(nodes)}")

        # The export may carry a per-layer collection name in _doc_meta; prefer
        # it over the visual Krita group (so collections round-trip even when
        # the document uses a single group).
        meta_by_name = {
            L.get("name"): L.get("group") for L in (_doc_meta or {}).get("layers", [])
        }

        def _read_pixels(node, t=None):
            # pixelData() (t=None) reads the CURRENT frame and works for static
            # layers; pixelDataAtTime(t) reads a specific keyframe and returns 0
            # bytes when there is no keyframe at t.
            try:
                raw = (
                    bytes(node.pixelData(0, 0, width, height))
                    if t is None
                    else bytes(node.pixelDataAtTime(0, 0, width, height, t))
                )
            except Exception as exc:  # noqa: BLE001
                print("BRIDGE: pixelData failed for", node.name(), "t=", t, ":", exc)
                _log("pixelData", f"FAILED {node.name()} t={t}: {exc}")
                raw = b""
            if len(raw) != expected:
                raw = b"\x00" * expected
            return raw

        def _save_png(raw, path):
            # .copy() makes the QImage OWN its buffer (see segfault notes).
            img = QImage(raw, width, height, width * 4, QImage.Format_ARGB32).copy()
            img.save(path, "PNG")

        # The animation range to scan for keyframes (Krita's full clip range).
        clip_start = int(doc.fullClipRangeStartTime())
        clip_end = int(doc.fullClipRangeEndTime())

        for idx, (node, group) in enumerate(reversed(nodes)):
            animated = bool(node.animated())
            # Prefer the collection name carried in _doc_meta, but fall back to
            # the visual Krita group when the meta value is missing/empty (GP
            # exports don't send a per-layer `group`, so meta_by_name has None
            # and we must use the group Krita created instead of "Krita").
            group = meta_by_name.get(node.name()) or group
            layer_info = {
                "name": node.name(),
                "group": group,
                "animated": animated,
                "frames": [],
                "opacity": node.opacity(),
                "visible": node.visible(),
            }
            if animated:
                keyframes = [
                    t for t in range(clip_start, clip_end + 1) if node.hasKeyframeAtTime(t)
                ]
                if not keyframes:
                    keyframes = [int(time)]  # fallback: current frame only
                for t in keyframes:
                    raw = _read_pixels(node, t)
                    path = os.path.join(out_dir, f"layer_{idx:02d}_f{t:04d}.png")
                    _save_png(raw, path)
                    layer_info["frames"].append({"frame": t, "file": path})
                _log("saved", f"{idx} {node.name()} animated={len(keyframes)} keyframes")
            else:
                raw = _read_pixels(node)
                path = os.path.join(out_dir, f"layer_{idx:02d}.png")
                _save_png(raw, path)
                layer_info["frames"].append({"frame": 1, "file": path})
                _log("saved", f"{idx} {node.name()} static single frame")
            layers.append(layer_info)
            set_status(
                f"Exported layer {idx + 1}/{len(nodes)}: {node.name()} "
                f"({len(layer_info['frames'])} frame(s))"
            )

        message = {
            "type": MSG_IMPORT_BACK,
            "object_uuid": _current_object_uuid,
            "width": width,
            "height": height,
            "fps": doc.framesPerSecond(),
            "frame_start": clip_start,
            "frame_end": clip_end,
            "frame_number": time,
            "layers": layers,
        }
        _log("send", f"{len(layers)} layers to Blender")
        ok = client.send(message)
        set_status(
            f"Sent {len(layers)} layer(s) to Blender" if ok else "Blender not connected"
        )
        return ok
    except Exception as exc:  # noqa: BLE001
        set_status(f"Send back error: {exc}")
        print("BRIDGE send_back error:", exc)
        _log("send_back", f"ERROR: {type(exc).__name__}: {exc}")
        return False
