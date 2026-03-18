"""Calibration flow — guides user to sit straight and captures baseline."""

from __future__ import annotations

import logging
import threading
from typing import Callable

import cv2
import gi
import numpy as np

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from dorso.camera_detector import CameraDetector, _model_path
from dorso.camera_hub import CameraHub
from dorso.i18n import _
from dorso.landmark_overlay import detect_and_draw
from dorso.models import CalibrationData

logger = logging.getLogger(__name__)


class CalibrationDialog:
    """Calibration dialog with live camera preview and landmarks."""

    def __init__(
        self,
        hub: CameraHub,
        detector: CameraDetector,
        on_complete: Callable[[CalibrationData | None], None],
        parent: Gtk.Window | None = None,
    ) -> None:
        self._hub = hub
        self._detector = detector
        self._on_complete = on_complete
        self._preview_subscribed = False
        self._landmarker = None
        self._landmarker_lock = threading.Lock()

        self._window = Gtk.Window(title=_("Dorso — Calibration"))
        self._window.set_default_size(460, -1)
        self._window.set_resizable(False)
        if parent:
            self._window.set_transient_for(parent)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)

        self._label = Gtk.Label()
        self._label.set_markup(_(
            "<big><b>Posture calibration</b></big>\n\n"
            "Sit up straight in your best\n"
            "posture, then click\n"
            "<b>Calibrate</b>."
        ))
        self._label.set_justify(Gtk.Justification.CENTER)
        box.append(self._label)

        # Camera preview
        frame = Gtk.Frame()
        self._preview = Gtk.Picture()
        self._preview.set_size_request(320, 240)
        self._preview.set_content_fit(Gtk.ContentFit.CONTAIN)
        frame.set_child(self._preview)
        frame.set_halign(Gtk.Align.CENTER)
        box.append(frame)

        self._spinner = Gtk.Spinner()
        box.append(self._spinner)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_halign(Gtk.Align.CENTER)

        self._calibrate_btn = Gtk.Button(label=_("Calibrate"))
        self._calibrate_btn.add_css_class("suggested-action")
        self._calibrate_btn.set_size_request(140, -1)
        self._calibrate_btn.connect("clicked", self._on_calibrate)
        btn_box.append(self._calibrate_btn)

        self._cancel_btn = Gtk.Button(label=_("Cancel"))
        self._cancel_btn.connect("clicked", self._on_cancel)
        btn_box.append(self._cancel_btn)

        box.append(btn_box)
        self._window.set_child(box)
        self._window.connect("close-request", self._on_close)

    def show(self) -> None:
        self._window.set_visible(True)
        self._start_preview()

    def present(self) -> None:
        """Bring existing window to front."""
        self._window.present()

    # -- Camera preview via hub --

    def _start_preview(self) -> None:
        self._ensure_landmarker()
        self._preview_subscribed = True
        self._hub.subscribe("cal_preview", self._on_preview_frame, fps=15.0)

    def _stop_preview(self) -> None:
        if self._preview_subscribed:
            self._hub.unsubscribe("cal_preview")
            self._preview_subscribed = False
        with self._landmarker_lock:
            if self._landmarker:
                self._landmarker.close()
                self._landmarker = None

    def _ensure_landmarker(self) -> None:
        if self._landmarker is not None:
            return
        try:
            from mediapipe.tasks.python import vision
            from mediapipe.tasks.python.core import base_options as bo

            model = _model_path()
            options = vision.PoseLandmarkerOptions(
                base_options=bo.BaseOptions(model_asset_path=str(model)),
                running_mode=vision.RunningMode.IMAGE,
                num_poses=1,
            )
            self._landmarker = vision.PoseLandmarker.create_from_options(options)
        except Exception:
            self._landmarker = None

    def _on_preview_frame(self, frame: np.ndarray) -> None:
        """Called from hub thread — draw landmarks, flip, convert, dispatch."""
        frame = cv2.flip(frame, 1)
        with self._landmarker_lock:
            if self._landmarker:
                frame = detect_and_draw(self._landmarker, frame)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, _ = frame.shape
        data = frame.tobytes()
        GLib.idle_add(self._update_preview, data, w, h)

    def _update_preview(self, data: bytes, w: int, h: int) -> bool:
        try:
            gbytes = GLib.Bytes.new(data)
            texture = Gdk.MemoryTexture.new(
                w, h, Gdk.MemoryFormat.R8G8B8, gbytes, w * 3
            )
            self._preview.set_paintable(texture)
        except Exception:
            pass
        return False

    # -- Calibration --

    def _on_calibrate(self, button: Gtk.Button) -> None:
        self._calibrate_btn.set_sensitive(False)
        self._cancel_btn.set_sensitive(False)
        self._label.set_markup(_(
            "<big><b>Calibrating…</b></big>\n"
            "\n"
            "Stay still for a few\n"
            "seconds."
        ))
        self._spinner.set_spinning(True)
        self._stop_preview()

        self._detector.calibrate(self._on_calibration_done)

    def _on_calibration_done(self, data: CalibrationData | None) -> None:
        """Called from detector thread — dispatch to main thread."""
        GLib.idle_add(self._finish, data)

    def _finish(self, data: CalibrationData | None) -> bool:
        self._spinner.set_spinning(False)
        self._stop_preview()
        self._window.set_visible(False)
        self._window.destroy()
        self._on_complete(data)
        return False

    def _on_cancel(self, button: Gtk.Button) -> None:
        self._stop_preview()
        self._window.set_visible(False)
        self._window.destroy()
        self._on_complete(None)

    def _on_close(self, window: Gtk.Window) -> bool:
        self._stop_preview()
        self._on_complete(None)
        return False
