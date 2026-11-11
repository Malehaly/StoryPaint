"""GP3 <-> domain <-> SVG adapters (requires bpy).

Imported lazily by `blender/__init__.py`; keeps `core/` and `domain/` headless.
"""

from __future__ import annotations

import bpy

from ..core import svg as svgmod
from ..domain.model import FrameData, LayerData, PointData, StrokeData


def _frame(layer, frame_number):
    """Return the GreasePencilFrame at frame_number (positional index != number)."""
    for f in layer.frames:
        if f.frame_number == frame_number:
            return f
    return None


def frame_from_gp(gpd, frame_number: int) -> FrameData:
    """Read a GreasePencil datablock's frame into a headless FrameData."""
    frame = FrameData(frame_number=frame_number)
    for layer in gpd.layers:
        layer_data = LayerData(name=layer.name)
        fr = _frame(layer, frame_number)
        if fr is None:
            frame.layers.append(layer_data)
            continue
        for stroke in fr.drawing.strokes:
            color = (0.0, 0.0, 0.0, 1.0)
            if 0 <= stroke.material_index < len(gpd.materials):
                style = gpd.materials[stroke.material_index].grease_pencil
                if style is not None:
                    color = tuple(style.color)
            stroke_data = StrokeData(
                material_index=stroke.material_index,
                color=color,
            )
            for pt in stroke.points:
                stroke_data.points.append(
                    PointData(
                        position=tuple(pt.position),
                        radius=pt.radius,
                        opacity=pt.opacity,
                        vertex_color=tuple(pt.vertex_color),
                    )
                )
            layer_data.strokes.append(stroke_data)
        frame.layers.append(layer_data)
    return frame


def frame_to_gp(gpd, frame_data: FrameData, replace: bool = False):
    """Write a FrameData into a GP datablock.

    With ``replace=True`` the matching layer's frame strokes are cleared first
    (import-back semantics); otherwise strokes are appended.
    """
    for layer_data in frame_data.layers:
        layer = next((l for l in gpd.layers if l.name == layer_data.name), None)
        if layer is None:
            layer = gpd.layers.new(layer_data.name)
        fr = _frame(layer, frame_data.frame_number)
        if fr is None:
            fr = layer.frames.new(frame_data.frame_number)
        drawing = fr.drawing
        if replace:
            count = len(drawing.strokes)
            if count:
                drawing.remove_strokes(indices=list(range(count)))
        for stroke_data in layer_data.strokes:
            drawing.add_strokes([len(stroke_data.points)])
            stroke = drawing.strokes[-1]
            stroke.material_index = stroke_data.material_index
            for i, pt in enumerate(stroke_data.points):
                sp = stroke.points[i]
                sp.position = pt.position
                sp.radius = pt.radius
                sp.opacity = pt.opacity
                sp.vertex_color = pt.vertex_color


def gp_to_svg_text(gpd, frame_number: int) -> str:
    """Serialize the GP datablock's frame to the own-format SVG."""
    return svgmod.frame_to_svg(frame_from_gp(gpd, frame_number))


def svg_text_to_gp(svg_text: str, gpd, frame_number: int, replace: bool = False):
    """Parse own-format SVG and write its content into the GP datablock."""
    frame_to_gp(gpd, svgmod.svg_to_frame(svg_text), replace=replace)
