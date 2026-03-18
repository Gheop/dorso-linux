"""First-launch onboarding wizard — welcome, camera preview + calibration, done."""

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


class OnboardingWindow:
    """Three-step onboarding: welcome → camera + calibration → done."""

    def __init__(
        self,
        hub: CameraHub,
        detector: CameraDetector,
        on_complete: Callable[[CalibrationData | None], None],
    ) -> None:
        self._hub = hub
        self._detector = detector
        self._on_complete = on_complete
        self._preview_subscribed = False
        self._landmarker = None
        self._landmarker_lock = threading.Lock()

        self._window = Gtk.Window(title="Dorso")
        self._window.set_default_size(500, 420)
        self._window.set_resizable(False)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        self._stack.set_transition_duration(300)

        self._stack.add_named(self._build_welcome(), "welcome")
        self._stack.add_named(self._build_camera(), "camera")
        self._stack.add_named(self._build_done(), "done")

        self._window.set_child(self._stack)
        self._window.connect("close-request", self._on_close)

    def show(self) -> None:
        self._window.set_visible(True)

    # -- Page 1: Welcome --

    def _build_welcome(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(40)
        box.set_margin_bottom(32)
        box.set_margin_start(40)
        box.set_margin_end(40)
        box.set_valign(Gtk.Align.CENTER)

        title = Gtk.Label()
        title.set_markup(f"<span size='xx-large'><b>{_('Welcome to Dorso')}</b></span>")
        box.append(title)

        desc = Gtk.Label()
        desc.set_markup(_(
            "Dorso monitors your posture via webcam\n"
            "and shows a <b>red glow</b> when you slouch.\n\n"
            "The overlay is transparent and doesn't\n"
            "interfere with mouse or keyboard."
        ))
        desc.set_justify(Gtk.Justification.CENTER)
        desc.set_wrap(True)
        box.append(desc)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        box.append(spacer)

        btn = Gtk.Button(label=_("Get started →"))
        btn.add_css_class("suggested-action")
        btn.add_css_class("pill")
        btn.set_halign(Gtk.Align.CENTER)
        btn.set_size_request(200, -1)
        btn.connect("clicked", lambda b: self._go_to_camera())
        box.append(btn)

        return box

    # -- Page 2: Camera preview + calibration --

    def _build_camera(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(32)
        box.set_margin_end(32)

        title = Gtk.Label()
        title.set_markup(f"<big><b>{_('Calibration')}</b></big>")
        box.append(title)

        self._camera_label = Gtk.Label()
        self._camera_label.set_markup(_(
            "Sit <b>up straight</b> in your best posture.\n"
            "Make sure you are visible in the preview."
        ))
        self._camera_label.set_justify(Gtk.Justification.CENTER)
        self._camera_label.set_wrap(True)
        box.append(self._camera_label)

        # Camera preview
        frame = Gtk.Frame()
        self._preview = Gtk.Picture()
        self._preview.set_size_request(320, 240)
        self._preview.set_content_fit(Gtk.ContentFit.CONTAIN)
        frame.set_child(self._preview)
        frame.set_halign(Gtk.Align.CENTER)
        box.append(frame)

        # Spinner (hidden until calibrating)
        self._spinner = Gtk.Spinner()
        box.append(self._spinner)

        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_halign(Gtk.Align.CENTER)

        self._cal_btn = Gtk.Button(label=_("Calibrate"))
        self._cal_btn.add_css_class("suggested-action")
        self._cal_btn.set_size_request(140, -1)
        self._cal_btn.connect("clicked", self._on_calibrate)
        btn_box.append(self._cal_btn)

        self._skip_btn = Gtk.Button(label=_("Cancel"))
        self._skip_btn.connect("clicked", self._on_skip)
        btn_box.append(self._skip_btn)

        box.append(btn_box)

        return box

    # -- Page 3: Done --

    def _build_done(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(40)
        box.set_margin_bottom(32)
        box.set_margin_start(40)
        box.set_margin_end(40)
        box.set_valign(Gtk.Align.CENTER)

        title = Gtk.Label()
        title.set_markup(f"<span size='xx-large'><b>{_('All set!')}</b></span>")
        box.append(title)

        desc = Gtk.Label()
        desc.set_markup(_(
            "Dorso is now running in the background.\n\n"
            "• <b>Tray icon</b> — real-time posture status\n"
            "• <b>Settings</b> — warning mode, color, sensitivity\n"
            "• <b>Analytics</b> — daily score and history"
        ))
        desc.set_justify(Gtk.Justification.CENTER)
        desc.set_wrap(True)
        box.append(desc)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        box.append(spacer)

        btn = Gtk.Button(label=_("Start"))
        btn.add_css_class("suggested-action")
        btn.add_css_class("pill")
        btn.set_halign(Gtk.Align.CENTER)
        btn.set_size_request(200, -1)
        btn.connect("clicked", self._on_finish)
        box.append(btn)

        return box

    # -- Navigation --

    def _go_to_camera(self) -> None:
        self._stack.set_visible_child_name("camera")
        self._start_preview()

    def _go_to_done(self) -> None:
        self._stop_preview()
        self._stack.set_visible_child_name("done")

    # -- Camera preview via hub --

    def _start_preview(self) -> None:
        self._ensure_landmarker()
        self._preview_subscribed = True
        self._hub.subscribe("onboarding_preview", self._on_preview_frame, fps=15.0)

    def _stop_preview(self) -> None:
        if self._preview_subscribed:
            self._hub.unsubscribe("onboarding_preview")
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

    def _show_camera_error(self) -> bool:
        self._camera_label.set_markup(_(
            "<b>Camera not found</b>\n\n"
            "Make sure your webcam is plugged in\n"
            "and try again."
        ))
        self._cal_btn.set_sensitive(False)
        return False

    # -- Calibration --

    def _on_calibrate(self, button: Gtk.Button) -> None:
        self._cal_btn.set_sensitive(False)
        self._skip_btn.set_sensitive(False)
        self._camera_label.set_markup(_(
            "<big><b>Calibrating…</b></big>\n"
            "Stay still for a few seconds."
        ))
        self._spinner.set_spinning(True)
        self._stop_preview()
        self._detector.calibrate(self._on_calibration_done)

    def _on_calibration_done(self, data: CalibrationData | None) -> None:
        GLib.idle_add(self._handle_calibration_result, data)

    def _handle_calibration_result(self, data: CalibrationData | None) -> bool:
        self._spinner.set_spinning(False)
        if data and data.is_valid:
            self._calibration_data = data
            self._go_to_done()
        else:
            self._camera_label.set_markup(_(
                "<b>Calibration failed</b>\n\n"
                "Make sure you are clearly visible to the camera\n"
                "and try again."
            ))
            self._cal_btn.set_sensitive(True)
            self._skip_btn.set_sensitive(True)
            self._start_preview()
        return False

    # -- Finish / Cancel --

    def _on_finish(self, button: Gtk.Button) -> None:
        self._close_and_complete(getattr(self, "_calibration_data", None))

    def _on_skip(self, button: Gtk.Button) -> None:
        self._close_and_complete(None)

    def _on_close(self, window: Gtk.Window) -> bool:
        self._stop_preview()
        self._on_complete(None)
        return False

    def _close_and_complete(self, data: CalibrationData | None) -> None:
        self._stop_preview()
        self._window.set_visible(False)
        self._window.destroy()
        self._on_complete(data)
