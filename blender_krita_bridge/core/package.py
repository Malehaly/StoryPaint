"""Bridge package assembly (headless; no bpy).

Writes a `manifest.json` plus one SVG per (layer, frame) under
`exports/<object_uuid>/layer_<i>/frame_<n>.svg`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ..common import ids
from ..domain.model import FrameData
from . import hashes, manifest as mf, protocol, svg as svgmod


def write_package(
    package_dir,
    *,
    object_uuid: str,
    object_name: str,
    data_name: str,
    frame_data: FrameData,
    matrix_world,
    scene_name: str,
    fps: float,
    source_version: str,
    target_version: str = "5.x",
) -> mf.Manifest:
    """Write a bridge package and return the built Manifest."""
    package_dir = Path(package_dir)
    object_dir = package_dir / "exports" / object_uuid

    object_entry = mf.ObjectEntry(
        object_uuid=object_uuid,
        object_name_at_export=object_name,
        data_name_at_export=data_name,
        matrix_world=[list(row) for row in matrix_world],
        coordinate_mode=protocol.COORDINATE_2D,
    )

    for li, layer in enumerate(frame_data.layers):
        layer_id = str(li)
        layer_dir = object_dir / f"layer_{layer_id}"
        layer_dir.mkdir(parents=True, exist_ok=True)

        single = FrameData(frame_number=frame_data.frame_number, layers=[layer])
        svg_text = svgmod.frame_to_svg(single)
        svg_path = layer_dir / f"frame_{frame_data.frame_number}.svg"
        svg_path.write_text(svg_text, encoding="utf-8")

        object_entry.layers.append(
            mf.LayerEntry(
                layer_id=layer_id,
                layer_name=layer.name,
                layer_order=li,
                frames=[
                    mf.FrameEntry(
                        frame_number=frame_data.frame_number,
                        export_id=f"{object_uuid}:{layer_id}:{frame_data.frame_number}",
                        format="svg",
                        path=svg_path.relative_to(package_dir).as_posix(),
                        sha256=hashes.sha256_file(svg_path),
                        status="exported",
                    )
                ],
            )
        )

    manifest = mf.Manifest(
        source={"application": "Blender", "version": source_version},
        target={"application": "Krita", "version": target_version},
        session_id=ids.new_uuid(),
        created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        scene=mf.SceneInfo(
            name=scene_name,
            frame_current=frame_data.frame_number,
            fps=fps,
        ),
        objects=[object_entry],
    )

    (package_dir / "manifest.json").write_text(manifest.to_json(indent=2), encoding="utf-8")
    return manifest
