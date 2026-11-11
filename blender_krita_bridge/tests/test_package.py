"""Headless tests for bridge package assembly (no Blender)."""

from blender_krita_bridge.core import hashes
from blender_krita_bridge.core.manifest import validate_manifest
from blender_krita_bridge.core.package import write_package
from blender_krita_bridge.domain.model import (
    FrameData,
    LayerData,
    PointData,
    StrokeData,
)

UUID = "11111111-1111-1111-1111-111111111111"
_IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def _frame() -> FrameData:
    return FrameData(
        frame_number=5,
        layers=[
            LayerData(
                name="Ink",
                strokes=[
                    StrokeData(
                        points=[
                            PointData(position=(0, 0, 0), radius=0.02),
                            PointData(position=(1, 0, 0), radius=0.02),
                        ],
                        color=(1, 0, 0, 1),
                    )
                ],
            )
        ],
    )


def test_write_package(tmp_path):
    manifest = write_package(
        tmp_path,
        object_uuid=UUID,
        object_name="GP",
        data_name="GPData",
        frame_data=_frame(),
        matrix_world=_IDENTITY,
        scene_name="Scene",
        fps=24.0,
        source_version="5.2.2",
    )
    assert validate_manifest(manifest) == []

    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()

    svg_path = tmp_path / "exports" / UUID / "layer_0" / "frame_5.svg"
    assert svg_path.exists()
    assert svg_path.read_text(encoding="utf-8").startswith("<?xml")

    frame_entry = manifest.objects[0].layers[0].frames[0]
    assert frame_entry.frame_number == 5
    assert frame_entry.path == f"exports/{UUID}/layer_0/frame_5.svg"
    assert frame_entry.sha256 == hashes.sha256_file(svg_path)
    assert manifest.scene.frame_current == 5
    assert manifest.scene.fps == 24.0
