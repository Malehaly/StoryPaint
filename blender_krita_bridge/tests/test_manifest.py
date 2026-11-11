"""Manifest build/parse/validate round-trip tests (headless)."""

from blender_krita_bridge.core.manifest import (
    FrameEntry,
    LayerEntry,
    Manifest,
    ObjectEntry,
    validate_manifest,
)
from blender_krita_bridge.core.protocol import SCHEMA_VERSION


def _sample_manifest() -> Manifest:
    return Manifest(
        session_id="session-1",
        created_utc="2026-10-21T00:00:00Z",
        objects=[
            ObjectEntry(
                object_uuid="11111111-1111-1111-1111-111111111111",
                object_name_at_export="GP_Character",
                data_name_at_export="GP_Character_Data",
                layers=[
                    LayerEntry(
                        layer_id="layer-1",
                        layer_name="Ink",
                        layer_order=0,
                        frames=[
                            FrameEntry(
                                frame_number=1,
                                export_id="export-1",
                                format="svg",
                                path=(
                                    "exports/11111111-1111-1111-1111-111111111111/"
                                    "layer_layer-1/frame_1.svg"
                                ),
                                sha256="abc",
                            )
                        ],
                    )
                ],
            )
        ],
    )


def test_manifest_dict_round_trip():
    manifest = _sample_manifest()
    data = manifest.to_dict()
    parsed = Manifest.from_dict(data)
    assert parsed.to_dict() == data
    assert parsed.schema_version == SCHEMA_VERSION


def test_manifest_json_round_trip():
    manifest = _sample_manifest()
    parsed = Manifest.from_json(manifest.to_json())
    assert parsed.objects[0].object_uuid == manifest.objects[0].object_uuid
    assert parsed.objects[0].layers[0].frames[0].format == "svg"


def test_validate_valid_manifest_passes():
    assert validate_manifest(_sample_manifest()) == []


def test_validate_missing_session_fails():
    manifest = _sample_manifest()
    manifest.session_id = ""
    assert any("session_id" in e for e in validate_manifest(manifest))


def test_validate_empty_objects_fails():
    manifest = Manifest(session_id="session-1")
    assert any("objects" in e for e in validate_manifest(manifest))


def test_validate_unknown_schema_version_fails():
    manifest = _sample_manifest()
    manifest.schema_version = "999.0"
    assert any("schema_version" in e for e in validate_manifest(manifest))


def test_validate_duplicate_uuid_fails():
    manifest = _sample_manifest()
    manifest.objects.append(ObjectEntry(object_uuid=manifest.objects[0].object_uuid))
    assert any("duplicate object_uuid" in e for e in validate_manifest(manifest))


def test_validate_missing_frame_path_fails():
    manifest = _sample_manifest()
    manifest.objects[0].layers[0].frames[0].path = ""
    assert any("has no path" in e for e in validate_manifest(manifest))
