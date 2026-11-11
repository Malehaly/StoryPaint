"""Canonical contract tests for the interchange protocol constants."""

from blender_krita_bridge.core import protocol


def test_schema_version_is_semver():
    assert protocol.SCHEMA_VERSION
    parts = protocol.SCHEMA_VERSION.split(".")
    assert len(parts) >= 2
    assert all(part.isdigit() for part in parts)


def test_bridge_name_is_set():
    assert protocol.BRIDGE_NAME == "BlenderKritaBridge"


def test_supported_formats_include_svg_and_png():
    assert protocol.FORMAT_SVG in protocol.SUPPORTED_FORMATS
    assert protocol.FORMAT_PNG in protocol.SUPPORTED_FORMATS


def test_default_coordinate_mode_is_2d_projected():
    assert protocol.COORDINATE_2D == "2d_projected"
