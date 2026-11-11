"""Add "Send back to Blender" to the layer docker's right-click menu.

Krita builds the layer context menu natively (``NodeView.contextMenuEvent``), so
there is no libkis hook to extend it. Instead a lightweight poller watches
``QApplication.activePopupWidget()``: the layer context menu is a top-level
(parentless) ``QMenu`` (Krita creates it on the stack and ``exec()``s it), so
when such a menu appears we append our action to it. Button menus and sub-menus
have a QObject parent, so they are ignored.
"""

from __future__ import annotations

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QMenu

from . import bridge

MENU_LABEL = "Send back to Blender"

_poll_timer = None  # module-level QTimer so it is never garbage-collected
_handled = set()  # stable keys of menus we've already appended to


def _stable_key(obj):
    """A key that stays constant across Python-wrapper rebuilds of the same object."""
    try:
        import sip

        return sip.unwrapinstance(obj)
    except Exception:  # noqa: BLE001
        return id(obj)


def _poll_tick():
    """Append our action to any open top-level (layer context) menu."""
    menu = QApplication.activePopupWidget()
    if isinstance(menu, QMenu) and menu.parent() is None:
        key = _stable_key(menu)
        if key in _handled:
            return
        _handled.add(key)
        for action in menu.actions():
            if action.text() == MENU_LABEL:
                return
        menu.addAction(MENU_LABEL, bridge.send_back)
        bridge._log("layer_menu", "appended 'Send back to Blender' to the menu")
    elif not isinstance(menu, QMenu):
        _handled.clear()  # no popup open — reset for the next menu


def start_poller():
    """Start (once) the poller that watches for the layer context menu."""
    global _poll_timer
    if _poll_timer is None:
        _poll_timer = QTimer()
        _poll_timer.timeout.connect(_poll_tick)
    if not _poll_timer.isActive():
        _poll_timer.start(100)


def install():
    """Back-compat alias: the poller does not need the docker to exist yet."""
    start_poller()
    return True


def install_when_ready():
    """Start the poller; it self-heals (nothing depends on the docker)."""
    start_poller()
