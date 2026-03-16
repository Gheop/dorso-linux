"""Calibration flow — guides user to sit straight and captures baseline."""

from __future__ import annotations

import logging
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from dorso.camera_detector import CameraDetector
from dorso.models import CalibrationData

logger = logging.getLogger(__name__)


class CalibrationDialog:
    """Simple calibration dialog: sit straight, press button, wait."""

    def __init__(
        self,
        detector: CameraDetector,
        on_complete: Callable[[CalibrationData | None], None],
        parent: Gtk.Window | None = None,
    ) -> None:
        self._detector = detector
        self._on_complete = on_complete

        self._window = Gtk.Window(title="Dorso — Calibration")
        self._window.set_default_size(400, 250)
        self._window.set_resizable(False)
        if parent:
            self._window.set_transient_for(parent)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)

        self._label = Gtk.Label()
        self._label.set_markup(
            "<big><b>Calibration de la posture</b></big>\n\n"
            "Asseyez-vous bien droit dans votre\n"
            "meilleure posture, puis cliquez sur\n"
            "<b>Calibrer</b>."
        )
        self._label.set_justify(Gtk.Justification.CENTER)
        box.append(self._label)

        self._spinner = Gtk.Spinner()
        box.append(self._spinner)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_halign(Gtk.Align.CENTER)

        self._calibrate_btn = Gtk.Button(label="Calibrer")
        self._calibrate_btn.add_css_class("suggested-action")
        self._calibrate_btn.connect("clicked", self._on_calibrate)
        btn_box.append(self._calibrate_btn)

        self._cancel_btn = Gtk.Button(label="Annuler")
        self._cancel_btn.connect("clicked", self._on_cancel)
        btn_box.append(self._cancel_btn)

        box.append(btn_box)
        self._window.set_child(box)

    def show(self) -> None:
        self._window.set_visible(True)

    def _on_calibrate(self, button: Gtk.Button) -> None:
        self._calibrate_btn.set_sensitive(False)
        self._label.set_markup(
            "<big><b>Calibration en cours…</b></big>\n\n"
            "Restez immobile pendant quelques\n"
            "secondes."
        )
        self._spinner.set_spinning(True)

        self._detector.calibrate(self._on_calibration_done)

    def _on_calibration_done(self, data: CalibrationData | None) -> None:
        """Called from detector thread — dispatch to main thread."""
        GLib.idle_add(self._finish, data)

    def _finish(self, data: CalibrationData | None) -> None:
        self._spinner.set_spinning(False)
        self._window.set_visible(False)
        self._window.destroy()
        self._on_complete(data)

    def _on_cancel(self, button: Gtk.Button) -> None:
        self._window.set_visible(False)
        self._window.destroy()
        self._on_complete(None)
