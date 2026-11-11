"""Package manifest model, build and validation (headless; no bpy).

The manifest is the part of the bridge package that never leaves Blender's
control: it carries identity (UUIDs), transforms, scene context and file hashes
that must NOT be inferred from the editable SVG/PNG files.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .protocol import BRIDGE_NAME, SCHEMA_VERSION

_IDENTITY_MATRIX = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


@dataclass
class ProjectionInfo:
    """How 3D GP content was projected to the 2D canvas at export time."""

    camera_name: str | None = None
    view_name: str | None = None
    width: int = 0
    height: int = 0
    units: str = "pixels"


@dataclass
class FrameEntry:
    frame_number: int
    export_id: str
    format: str
    path: str
    sha256: str
    status: str = "exported"


@dataclass
class LayerEntry:
    layer_id: str
    layer_name: str
    layer_order: int
    frames: list[FrameEntry] = field(default_factory=list)


@dataclass
class ObjectEntry:
    object_uuid: str
    object_name_at_export: str = ""
    data_name_at_export: str = ""
    object_type: str = "GREASEPENCIL"
    matrix_world: list[list[float]] = field(
        default_factory=lambda: [row[:] for row in _IDENTITY_MATRIX]
    )
    coordinate_mode: str = "2d_projected"
    projection: ProjectionInfo = field(default_factory=ProjectionInfo)
    layers: list[LayerEntry] = field(default_factory=list)


@dataclass
class SceneInfo:
    name: str
    frame_current: int
    fps: float


@dataclass
class Manifest:
    """Top-level package descriptor (one per export operation)."""

    schema_version: str = SCHEMA_VERSION
    bridge_name: str = BRIDGE_NAME
    source: dict[str, str] = field(default_factory=dict)
    target: dict[str, str] = field(default_factory=dict)
    session_id: str = ""
    created_utc: str = ""
    scene: SceneInfo = field(default_factory=lambda: SceneInfo("", 1, 24.0))
    objects: list[ObjectEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Manifest":
        scene = data.get("scene") or {}
        objects: list[ObjectEntry] = []
        for obj in data.get("objects") or []:
            projection = obj.get("projection") or {}
            layers: list[LayerEntry] = []
            for layer in obj.get("layers") or []:
                frames = [FrameEntry(**f) for f in (layer.get("frames") or [])]
                layers.append(
                    LayerEntry(
                        layer_id=layer["layer_id"],
                        layer_name=layer.get("layer_name", ""),
                        layer_order=layer.get("layer_order", 0),
                        frames=frames,
                    )
                )
            objects.append(
                ObjectEntry(
                    object_uuid=obj["object_uuid"],
                    object_name_at_export=obj.get("object_name_at_export", ""),
                    data_name_at_export=obj.get("data_name_at_export", ""),
                    object_type=obj.get("object_type", "GREASEPENCIL"),
                    matrix_world=obj.get("matrix_world")
                    or [row[:] for row in _IDENTITY_MATRIX],
                    coordinate_mode=obj.get("coordinate_mode", "2d_projected"),
                    projection=ProjectionInfo(**projection),
                    layers=layers,
                )
            )
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            bridge_name=data.get("bridge_name", BRIDGE_NAME),
            source=data.get("source") or {},
            target=data.get("target") or {},
            session_id=data.get("session_id", ""),
            created_utc=data.get("created_utc", ""),
            scene=SceneInfo(
                name=scene.get("name", ""),
                frame_current=scene.get("frame_current", 1),
                fps=scene.get("fps", 24.0),
            ),
            objects=objects,
        )

    @classmethod
    def from_json(cls, text: str) -> "Manifest":
        return cls.from_dict(json.loads(text))


def validate_manifest(manifest: Manifest) -> list[str]:
    """Return a list of validation errors (empty list == valid).

    Checks schema version, identity uniqueness, and presence of referenced
    files.
    """
    errors: list[str] = []

    if not manifest.schema_version:
        errors.append("schema_version is missing")
    elif manifest.schema_version != SCHEMA_VERSION:
        errors.append(
            f"schema_version {manifest.schema_version!r} is not supported "
            f"(expected {SCHEMA_VERSION!r})"
        )

    if not manifest.session_id:
        errors.append("session_id is missing")

    if not manifest.objects:
        errors.append("objects is missing or empty")

    seen_uuids: set[str] = set()
    for obj in manifest.objects:
        if not obj.object_uuid:
            errors.append("an object is missing object_uuid")
        elif obj.object_uuid in seen_uuids:
            errors.append(f"duplicate object_uuid {obj.object_uuid!r}")
        seen_uuids.add(obj.object_uuid)

        for layer in obj.layers:
            for frame in layer.frames:
                if not frame.path:
                    errors.append(
                        f"object {obj.object_uuid} frame {frame.frame_number} "
                        "has no path"
                    )

    return errors


def load_manifest(path: str | Path) -> Manifest:
    """Read and parse a manifest file from disk."""
    return Manifest.from_json(Path(path).read_text(encoding="utf-8"))
