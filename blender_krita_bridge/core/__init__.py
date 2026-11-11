"""Interchange contract layer (headless; no `bpy` / `mathutils` imports).

This layer owns the on-disk package contract: protocol constants, the package
manifest model, and file hashing.
"""

from .protocol import (
    BRIDGE_NAME,
    COORDINATE_2D,
    FORMAT_PNG,
    FORMAT_SVG,
    SCHEMA_VERSION,
    SUPPORTED_FORMATS,
)

__all__ = [
    "BRIDGE_NAME",
    "COORDINATE_2D",
    "FORMAT_PNG",
    "FORMAT_SVG",
    "SCHEMA_VERSION",
    "SUPPORTED_FORMATS",
]
