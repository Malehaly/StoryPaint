"""Headless tests for the own-format SVG writer/reader (no Blender)."""

from blender_krita_bridge.core import svg
from blender_krita_bridge.domain.model import (
    FrameData,
    LayerData,
    PointData,
    StrokeData,
)


def _sample_frame() -> FrameData:
    return FrameData(
        frame_number=3,
        layers=[
            LayerData(
                name="Ink",
                strokes=[
                    StrokeData(
                        points=[
                            PointData(position=(0.0, 0.0, 0.0), radius=0.02),
                            PointData(position=(0.5, 0.5, 0.0), radius=0.02),
                            PointData(position=(1.0, 0.0, 0.0), radius=0.02),
                        ],
                        color=(1.0, 0.0, 0.0, 1.0),
                    )
                ],
            ),
            LayerData(
                name="Shade",
                strokes=[
                    StrokeData(
                        points=[
                            PointData(position=(0.2, 0.8, 0.0), radius=0.05),
                            PointData(position=(0.8, 0.8, 0.0), radius=0.05),
                        ],
                        color=(0.0, 0.2, 1.0, 1.0),
                    )
                ],
            ),
        ],
    )


def test_round_trip_lossless_channel():
    frame = _sample_frame()
    parsed = svg.svg_to_frame(svg.frame_to_svg(frame))
    assert parsed.frame_number == 3
    assert [l.name for l in parsed.layers] == ["Ink", "Shade"]
    for orig_layer, new_layer in zip(frame.layers, parsed.layers):
        for orig_stroke, new_stroke in zip(orig_layer.strokes, new_layer.strokes):
            assert len(orig_stroke.points) == len(new_stroke.points)
            for op, np_ in zip(orig_stroke.points, new_stroke.points):
                for a, b in zip(op.position, np_.position):
                    assert abs(a - b) < 1e-5
                assert abs(op.radius - np_.radius) < 1e-5
            for a, b in zip(orig_stroke.color, new_stroke.color):
                assert abs(a - b) < 0.02  # 1/255 rounding on the hex channel


def test_visible_channel_only_drops_radius():
    """Without data-* the visible channel (d + stroke-width) must still parse."""
    text = svg.frame_to_svg(_sample_frame())
    # strip the lossless attributes to simulate a Krita edit keeping only d+stroke
    stripped = text.replace(' data-points="', ' data-dropped-points="')
    stripped = stripped.replace(' data-radii="', ' data-dropped-radii="')
    stripped = stripped.replace(' data-opacities="', ' data-dropped-opacities="')
    parsed = svg.svg_to_frame(stripped)
    ink = parsed.layers[0]
    assert len(ink.strokes[0].points) == 3
    # uniform-radius stroke: radius recovered from stroke-width
    assert abs(ink.strokes[0].points[0].radius - 0.02) < 1e-5


def test_hex_round_trip():
    assert svg.color_to_hex((1.0, 0.0, 0.0, 1.0)) == "#ff0000"
    assert svg.color_to_hex((0.0, 0.2, 1.0, 1.0)) == "#0033ff"
    r, g, b = svg.hex_to_color("#0033ff")
    assert abs(r - 0.0) < 1e-5 and abs(g - 0.2) < 0.01 and abs(b - 1.0) < 1e-5
