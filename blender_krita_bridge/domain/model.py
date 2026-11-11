"""Grease Pencil data model (headless; no bpy).

Pure dataclasses for the content the bridge exports/imports. The `blender/`
layer converts between these and `bpy` Grease Pencil objects; `core/svg.py`
serializes these to/from SVG.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PointData:
    position: tuple[float, float, float]
    radius: float = 0.01
    opacity: float = 1.0
    vertex_color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass
class StrokeData:
    points: list[PointData] = field(default_factory=list)
    material_index: int = 0
    # Resolved stroke color (from the material at export time); carried so the
    # SVG can be written without re-resolving materials.
    color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)


@dataclass
class LayerData:
    name: str
    strokes: list[StrokeData] = field(default_factory=list)


@dataclass
class FrameData:
    frame_number: int = 1
    layers: list[LayerData] = field(default_factory=list)
