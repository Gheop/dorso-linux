"""First-launch onboarding wizard — welcome, camera preview + calibration, done."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import cv2
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from dorso.camera_detector import CameraDetector
from dorso.i18n import _
from dorso.models import CalibrationData

logger = logging.getLogger(__name__)


class OnboardingWindow:
    """Three-step onboarding: welcome → camera + calibration → done."""

    def __init__(
        self,
        detector: CameraDetector,
        camera_id: int,
        on_complete: Callable[[CalibrationData | None], None],
    ) -> None:
        self._detector = detector
        self._camera_id = camera_id
        self._on_complete = on_complete
        self._preview_running = False
        self._preview_thread: threading.Thread | None = None

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

    # -- Camera preview --

    def _start_preview(self) -> None:
        self._preview_running = True
        self._preview_thread = threading.Thread(target=self._preview_loop, daemon=True)
        self._preview_thread.start()

    def _stop_preview(self) -> None:
        self._preview_running = False
        if self._preview_thread:
            self._preview_thread.join(timeout=2.0)
            self._preview_thread = None

    def _preview_loop(self) -> None:
        cap = cv2.VideoCapture(self._camera_id)
        if not cap.isOpened():
            GLib.idle_add(self._show_camera_error)
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        try:
            while self._preview_running:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue

                # Mirror horizontally for natural feel
                frame = cv2.flip(frame, 1)
                # BGR → RGB
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, c = frame.shape
                data = frame.tobytes()

                GLib.idle_add(self._update_preview, data, w, h)
                time.sleep(1 / 15)  # ~15 fps
        finally:
            cap.release()

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
