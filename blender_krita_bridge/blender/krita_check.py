"""Assisted install + health check for the Krita side of the bridge.

Blender is the "parent": this module detects whether the Krita plugin is
installed and activated, can install it (copying the bundled files into Krita's
``pykrita`` resources), and reports whether Krita is currently connected.

All filesystem checks are plain Python (Krita is never imported); the
"connected" signal comes from the bridge socket — Krita's plugin connects to
Blender on load, so a live connection proves the plugin is installed AND
activated AND Krita is open.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

import bpy

from . import connection

KRITA_PLUGIN_NAME = "krita_bridge"
KRITA_DESKTOP_NAME = "krita_bridge.desktop"

# Shown as the "Installation guide (README)" link at the bottom of the setup
# area. Points at the public README's installation section.
INSTALL_GUIDE_URL = "https://github.com/Malehaly/StoryPaint#installation"

_CACHE_TTL = 1.0  # seconds the offline checks (filesystem/process) are cached
_cache = None
_cache_time = 0.0


def _pykrita_dir():
    """Krita's ``pykrita`` resources folder, or ``None`` when not found."""
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            return os.path.join(base, "krita", "pykrita")
        return None
    xdg_data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser(
        "~/.local/share"
    )
    candidates = [
        os.path.join(xdg_data, "krita", "pykrita"),
        os.path.expanduser("~/Library/Application Support/krita/pykrita"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[0]


def _kritarc_paths():
    """Candidate paths for Krita's config file (``kritarc``).

    Standard installs keep it under the config dir; the Steam build on Windows
    writes it to ``%LOCALAPPDATA%\\kritarc`` (verified on this machine).
    """
    if os.name == "nt":
        paths = []
        local = os.environ.get("LOCALAPPDATA")
        roaming = os.environ.get("APPDATA")
        if local:
            paths.append(os.path.join(local, "kritarc"))
        if roaming:
            paths.append(os.path.join(roaming, "krita", "kritarc"))
        return paths
    xdg_config = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser(
        "~/.config"
    )
    return [
        os.path.join(xdg_config, "krita", "kritarc"),
        os.path.expanduser("~/Library/Preferences/kritarc"),
    ]


def krita_installed():
    """True when the Krita plugin files are present in ``pykrita``."""
    d = _pykrita_dir()
    if not d:
        return False
    return os.path.isfile(os.path.join(d, KRITA_DESKTOP_NAME)) and os.path.isdir(
        os.path.join(d, KRITA_PLUGIN_NAME)
    )


def krita_activated():
    """True when ``enable_krita_bridge=true`` is set in ``kritarc``.

    Returns ``False`` when at least one ``kritarc`` was found without the flag,
    and ``None`` when no ``kritarc`` could be located (activation unknown).
    """
    marker = "enable_{}=true".format(KRITA_PLUGIN_NAME).lower()
    found_any = False
    for path in _kritarc_paths():
        if not os.path.isfile(path):
            continue
        found_any = True
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.strip().lower() == marker:
                        return True
        except OSError:
            continue
    return False if found_any else None


def krita_running():
    """Best-effort check for a running Krita process; ``None`` when unknown.

    Match on raw bytes: ``tasklist`` outputs the OEM codepage (CP850) and
    decoding it as UTF-8 (``text=True``) fails inside Blender, yielding
    ``stdout=None``. Process names are ASCII, so a byte search is safe.
    """
    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq krita.exe"],
                capture_output=True,
                timeout=5,
            )
            return b"krita.exe" in (proc.stdout or b"").lower()
        except Exception:  # noqa: BLE001
            return None
    try:
        proc = subprocess.run(["pgrep", "-x", "krita"], capture_output=True, timeout=5)
        return bool((proc.stdout or b"").strip())
    except Exception:  # noqa: BLE001
        return None


def check_status(force=False):
    """Return the Krita-side health as a dict (cached ~1s when offline).

    Fields: ``connected`` (live socket), ``installed``, ``activated``
    (True/False/None), ``running`` (True/False/None), ``needs_restart``
    (installed + activated + running but not connected — Krita must be
    restarted to load a freshly-enabled plugin), ``ready``, ``pykrita_dir``.
    ``ready`` is True only when Krita is connected, which is the definitive
    "installed + activated + open" signal.
    """
    global _cache, _cache_time
    server = connection.BridgeServer.instance()
    connected = server.connected
    now = time.monotonic()

    if connected:
        # A live connection implies installed + activated + running, so skip the
        # (more expensive) filesystem/process checks entirely.
        status = {
            "connected": True,
            "installed": True,
            "activated": True,
            "running": True,
            "needs_restart": False,
            "pykrita_dir": _pykrita_dir(),
            "ready": True,
        }
        _cache = dict(status)
        _cache_time = now
        return status

    if not force and _cache is not None and (now - _cache_time) < _CACHE_TTL:
        return dict(_cache)

    status = {
        "connected": False,
        "installed": krita_installed(),
        "activated": krita_activated(),
        "running": krita_running(),
        "pykrita_dir": _pykrita_dir(),
        "ready": False,
    }
    # Everything is in place but Krita is running without the plugin loaded —
    # the user enabled it but forgot to restart (Krita loads plugins at startup).
    status["needs_restart"] = (
        status["installed"] and status["activated"] is True and status["running"] is True
    )
    _cache = dict(status)
    _cache_time = now
    return status


def _krita_plugin_source_dir():
    """Folder containing the Krita plugin to install (``krita_bridge/`` + desktop).

    In the dev repo this is ``krita_plugin/`` (so live edits are picked up); in a
    shipped zip it is the bundled ``krita_side/`` copy inside the addon package.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.normpath(os.path.join(here, "..", "..", "krita_plugin")),
        os.path.normpath(os.path.join(here, "..", "krita_side")),
    ]
    for c in candidates:
        if os.path.isfile(os.path.join(c, KRITA_DESKTOP_NAME)) and os.path.isdir(
            os.path.join(c, KRITA_PLUGIN_NAME)
        ):
            return c
    return None


def draw_status_block(layout, status):
    """Draw the Krita-side status lines (shared by the panel and the popup)."""
    if status["ready"]:
        layout.label(text="Krita connected — StoryPaint ready", icon="CHECKMARK")
        return

    if not status["installed"]:
        layout.label(text="Krita plugin not installed", icon="ERROR")
        layout.operator("bridge.install_krita_side", icon="IMPORT")
        layout.label(text="Then: Configure Krita → Python Plugin Manager", icon="INFO")
        layout.label(text="enable StoryPaint → restart Krita", icon="INFO")
        return

    if status["activated"] is False:
        layout.label(text="Installed — activate in Krita", icon="INFO")
        layout.label(text="Configure Krita → Python Plugin Manager", icon="INFO")
        layout.label(text="enable StoryPaint → restart Krita", icon="INFO")
        return

    # Installed + activated (or activation unknown) — Krita just isn't connected.
    if status.get("needs_restart"):
        layout.label(text="Activated — restart Krita to load StoryPaint", icon="ERROR")
        layout.label(text="Krita only loads plugins at startup", icon="INFO")
    elif status["running"] is False:
        layout.label(text="Open Krita — StoryPaint loads automatically", icon="INFO")
    else:
        layout.label(text="Krita not connected", icon="INFO")
        layout.label(text="Restart Krita or re-enable StoryPaint", icon="INFO")


class BRIDGE_OT_install_krita_side(bpy.types.Operator):
    """Copy the Krita plugin into Krita's pykrita folder (you still enable it there)."""
    bl_idname = "bridge.install_krita_side"
    bl_label = "Install Krita Side"
    bl_description = (
        "Copy the Krita plugin files into Krita's pykrita folder; then enable "
        "it in Krita's Python Plugin Manager and restart Krita"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        target = _pykrita_dir()
        if not target:
            self.report({"ERROR"}, "Krita resources folder not found — is Krita installed?")
            return {"CANCELLED"}
        src = _krita_plugin_source_dir()
        if not src:
            self.report({"ERROR"}, "Bundled Krita plugin files are missing")
            return {"CANCELLED"}
        try:
            os.makedirs(target, exist_ok=True)
            shutil.copytree(
                os.path.join(src, KRITA_PLUGIN_NAME),
                os.path.join(target, KRITA_PLUGIN_NAME),
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            shutil.copy2(
                os.path.join(src, KRITA_DESKTOP_NAME),
                os.path.join(target, KRITA_DESKTOP_NAME),
            )
        except OSError as exc:
            self.report({"ERROR"}, "Could not install Krita side: {}".format(exc))
            return {"CANCELLED"}
        check_status(force=True)
        self.report({"INFO"}, "Krita side installed to {}".format(target))
        return {"FINISHED"}


class BRIDGE_OT_check_krita_side(bpy.types.Operator):
    """Re-check the Krita side: running, installed and activated."""
    bl_idname = "bridge.check_krita_side"
    bl_label = "Check Krita Side"
    bl_description = (
        "Check whether Krita is open and the StoryPaint plugin is installed and "
        "activated"
    )
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        self._status = check_status(force=True)
        return context.window_manager.invoke_popup(self, width=380)

    def draw(self, context):
        draw_status_block(self.layout, self._status)

    def execute(self, context):
        # Fallback for scripted invocation (no popup): refresh + report only.
        status = check_status(force=True)
        if status["ready"]:
            self.report({"INFO"}, "StoryPaint is ready")
        else:
            self.report({"WARNING"}, "StoryPaint is not ready yet")
        return {"FINISHED"}


classes = (BRIDGE_OT_install_krita_side, BRIDGE_OT_check_krita_side)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
