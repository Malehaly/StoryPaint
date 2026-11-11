"""SVG serialization for GP strokes (headless; no bpy).

Own format: strokes become `<path stroke stroke-width fill="none">`
(centerline + thickness preserved, unlike Blender's native filled outline)
plus a lossless `data-*` channel.

Convention: SVG y-axis points DOWN, Blender y points UP — so the visible `d`
path stores a flipped Y; `data-points` keeps the unflipped 3D coordinates.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ..domain.model import FrameData, LayerData, PointData, StrokeData

SVG_NS = "http://www.w3.org/2000/svg"

_XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>\n'

# Display scale: pixels per Blender unit for the SVG `width`/`height`.
# Coordinates in `d` stay in Blender units (lossless); the viewBox does the
# scaling for viewers like Krita/browsers.
SVG_SCALE = 1000.0


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _c8(value: float) -> int:
    return max(0, min(255, int(round(value * 255))))


def color_to_hex(color: tuple[float, ...]) -> str:
    r, g, b = color[:3]
    return f"#{_c8(r):02x}{_c8(g):02x}{_c8(b):02x}"


def hex_to_color(hexstr: str) -> tuple[float, float, float]:
    h = hexstr.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def build_path_d(points) -> str:
    """Build an SVG `d` attribute from flipped (x, y) pairs."""
    return "M " + " L ".join(f"{x:.6f},{y:.6f}" for x, y in points)


def parse_path_d(d: str) -> list[tuple[float, float]]:
    """Parse our own `M x,y L x,y ...` path data (one point per segment)."""
    pts = []
    for seg in re.split(r"[MLZz]", d):
        seg = seg.replace(",", " ").strip()
        if not seg:
            continue
        nums = seg.split()
        if len(nums) >= 2:
            pts.append((float(nums[0]), float(nums[1])))
    return pts


def _set_viewbox(svg, points):
    if points:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
    else:
        min_x = min_y = 0.0
        max_x = max_y = 1.0
    pad = max(0.05 * max(max_x - min_x, max_y - min_y), 1e-6)
    min_x -= pad
    max_x += pad
    min_y -= pad
    max_y += pad
    w = max(max_x - min_x, 1e-6)
    h = max(max_y - min_y, 1e-6)
    svg.set("viewBox", f"{min_x:.6f} {min_y:.6f} {w:.6f} {h:.6f}")
    svg.set("width", f"{w * SVG_SCALE:.1f}px")
    svg.set("height", f"{h * SVG_SCALE:.1f}px")


def frame_to_svg(frame: FrameData) -> str:
    svg = ET.Element("svg", {"xmlns": SVG_NS, "version": "1.1"})
    meta = ET.SubElement(svg, "metadata")
    meta.text = "BlenderKritaBridge own-format v0.1"

    # Display viewBox from the flipped (SVG y-down) points; coords stay lossless.
    flipped_all = [
        (p.position[0], -p.position[1])
        for layer in frame.layers
        for stroke in layer.strokes
        for p in stroke.points
    ]
    _set_viewbox(svg, flipped_all)

    frame_el = ET.SubElement(svg, "g", {"id": f"blender_frame.{frame.frame_number}"})
    for li, layer in enumerate(frame.layers):
        layer_el = ET.SubElement(
            frame_el, "g", {"id": f"layer.{li}", "data-layer-name": layer.name}
        )
        for si, stroke in enumerate(layer.strokes):
            flipped = [(p.position[0], -p.position[1]) for p in stroke.points]
            width = (max((p.radius for p in stroke.points), default=0.01)) * 2.0
            ET.SubElement(
                layer_el,
                "path",
                {
                    "id": f"stroke.{si}",
                    "d": build_path_d(flipped),
                    "stroke": color_to_hex(stroke.color),
                    "stroke-width": f"{width:.6f}",
                    "stroke-opacity": f"{stroke.color[3]:.4f}",
                    "fill": "none",
                    "stroke-linecap": "round",
                    "stroke-linejoin": "round",
                    # lossless channel (our own; NOT preserved by a Krita edit)
                    "data-points": ";".join(
                        f"{p.position[0]:.6f},{p.position[1]:.6f},{p.position[2]:.6f}"
                        for p in stroke.points
                    ),
                    "data-radii": ";".join(f"{p.radius:.6f}" for p in stroke.points),
                    "data-opacities": ";".join(f"{p.opacity:.4f}" for p in stroke.points),
                },
            )
    ET.indent(svg, space="  ")
    return _XML_DECL + ET.tostring(svg, encoding="unicode")


def svg_to_frame(text: str) -> FrameData:
    root = ET.fromstring(text)
    frame = FrameData()
    for el in root.iter():
        if _local(el.tag) != "g":
            continue
        if (el.get("id") or "").startswith("blender_frame."):
            try:
                frame.frame_number = int(el.get("id").split(".", 1)[1])
            except (ValueError, TypeError):
                pass
            for layer_el in el:
                if _local(layer_el.tag) != "g":
                    continue
                layer = LayerData(
                    name=layer_el.get("data-layer-name") or layer_el.get("id") or "?"
                )
                for child in layer_el:
                    if _local(child.tag) == "path":
                        layer.strokes.append(_path_to_stroke(child))
                frame.layers.append(layer)
    return frame


def _path_to_stroke(path_el) -> StrokeData:
    color = (
        *hex_to_color(path_el.get("stroke", "#000000")),
        float(path_el.get("stroke-opacity", "1")),
    )
    stroke = StrokeData(color=color)
    if path_el.get("data-points"):
        points = []
        for chunk in path_el.get("data-points", "").split(";"):
            if not chunk:
                continue
            x, y, z = (float(v) for v in chunk.split(","))
            points.append(PointData(position=(x, y, z)))
        radii = [float(v) for v in path_el.get("data-radii", "").split(";") if v]
        opacs = [float(v) for v in path_el.get("data-opacities", "").split(";") if v]
        for i, pt in enumerate(points):
            pt.radius = radii[i] if i < len(radii) else 0.01
            pt.opacity = opacs[i] if i < len(opacs) else 1.0
        stroke.points = points
    else:
        pts2d = parse_path_d(path_el.get("d", ""))
        radius = float(path_el.get("stroke-width", 0.0)) / 2.0
        stroke.points = [
            PointData(position=(x, -y, 0.0), radius=radius) for x, y in pts2d
        ]
    return stroke


def frame_layers_to_svg(frame: FrameData) -> list[dict]:
    """Serialize each layer of a frame to its own SVG (for the socket push)."""
    return [
        {
            "name": layer.name,
            "svg": frame_to_svg(
                FrameData(frame_number=frame.frame_number, layers=[layer])
            ),
        }
        for layer in frame.layers
    ]
