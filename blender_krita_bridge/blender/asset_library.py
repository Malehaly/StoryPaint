"""Auto-register the StoryPaint asset library + catalog (for the Shot.000 asset).

The bundled startup ships ``Shot.000`` marked as a scene asset in the
``StoryPaint`` catalog. The catalog DEFINITION (UUID → path) must live in an
asset library the user has registered, otherwise the asset shows as unassigned.
This module creates a small library (bundled
``assets/asset_library/blender_assets.cats.txt``) and registers it in Blender's
preferences so the catalog resolves on any machine.
"""

from __future__ import annotations

import os

import bpy

LIBRARY_NAME = "StoryPaint"
CATALOG_NAME = "StoryPaint"
CATALOG_UUID = "157e5268-5993-4e9d-99c5-afac0e4462e2"

_CATS_TEMPLATE = (
    "# This is an Asset Catalog Definition file for Blender.\n"
    "VERSION 1\n\n"
    "{uuid}:{path}:{name}\n"
)


def _library_dir() -> str:
    """Directory of the bundled asset library (ships with the plugin)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "assets", "asset_library"))


def _cats_path() -> str:
    return os.path.join(_library_dir(), "blender_assets.cats.txt")


def _write_catalog_file() -> None:
    """Ensure the bundled catalog file exists with our StoryPaint catalog.

    Idempotent: never overwrites an existing catalog file.
    """
    os.makedirs(_library_dir(), exist_ok=True)
    cats = _cats_path()
    if os.path.isfile(cats):
        return
    try:
        with open(cats, "w", encoding="utf-8") as f:
            f.write(
                _CATS_TEMPLATE.format(
                    uuid=CATALOG_UUID, path=CATALOG_NAME, name=CATALOG_NAME
                )
            )
    except OSError:
        pass


def ensure_asset_library() -> None:
    """Register the StoryPaint asset library in preferences (idempotent).

    Checks whether a library named ``StoryPaint`` already exists: if it does we
    do NOT create a duplicate, we only make sure the bundled catalog file is
    present. On first run it also saves the preferences so the library survives
    a restart.
    """
    _write_catalog_file()
    libs = bpy.context.preferences.filepaths.asset_libraries
    for lib in libs:
        if lib.name == LIBRARY_NAME:
            return  # already registered
    try:
        lib = libs.new(name=LIBRARY_NAME, directory=_library_dir())
    except Exception:  # noqa: BLE001
        return
    try:
        bpy.ops.wm.save_userpref()
    except Exception:  # noqa: BLE001
        pass


classes = ()


def register() -> None:
    ensure_asset_library()


def unregister() -> None:
    # The library registration is a user preference; leave it in place on
    # disable so the user's assets keep resolving.
    pass
