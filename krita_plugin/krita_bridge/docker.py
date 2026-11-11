"""Docker with the bridge controls (Krita side)."""

from __future__ import annotations

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from krita import DockWidget

from . import bridge


class BridgeDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StoryPaint")

        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.status = QLabel(bridge.last_status)
        layout.addWidget(self.status)

        send_button = QPushButton("Send back to Blender")
        send_button.clicked.connect(self._send_back)
        layout.addWidget(send_button)

        self.setWidget(widget)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(300)

    def canvasChanged(self, canvas):
        pass

    def _refresh(self):
        self.status.setText(bridge.last_status)

    def _send_back(self):
        if bridge.send_back():
            bridge.set_status("Sent to Blender")
        else:
            self.status.setText(bridge.last_status)
