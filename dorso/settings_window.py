"""Settings window — GTK4 dialog using native Adwaita/GNOME styling."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from dorso.camera_hub import CameraHub
from dorso.i18n import _
from dorso.models import DetectionMode, WarningMode
from dorso.settings import Settings
from dorso.v4l2_cameras import list_cameras


def _autostart_path() -> Path:
    import os
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "autostart" / "dorso.desktop"


def _desktop_source() -> Path:
    return Path(__file__).parent.parent / "data" / "dorso.desktop"

logger = logging.getLogger(__name__)


class SettingsWindow:
    """Settings dialog using native GTK4/Adwaita CSS classes."""

    def __init__(
        self,
        hub: CameraHub,
        settings: Settings,
        on_changed: Callable[[Settings], None],
        on_recalibrate: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self._hub = hub
        self._settings = settings
        self._on_changed = on_changed
        self._on_recalibrate = on_recalibrate
        self._on_close_cb = on_close
        self._updating = False
        self._preview_subscribed = False

        self._window = Gtk.Window(title=_("Dorso — Settings"))
        self._window.set_default_size(440, 800)
        self._window.set_resizable(True)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        main_box.set_margin_top(20)
        main_box.set_margin_bottom(20)
        main_box.set_margin_start(20)
        main_box.set_margin_end(20)

        # ---- Header ----
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label="Dorso")
        title.add_css_class("title-1")
        title.set_halign(Gtk.Align.START)
        title_box.append(title)

        ver = Gtk.Label(label="v0.1.0 — Linux")
        ver.add_css_class("dim-label")
        ver.set_halign(Gtk.Align.START)
        title_box.append(ver)
        header.append(title_box)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)

        if self._on_recalibrate:
            recal_btn = Gtk.Button()
            btn_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            btn_icon = Gtk.Image.new_from_icon_name("view-refresh-symbolic")
            btn_content.append(btn_icon)
            btn_content.append(Gtk.Label(label=_("Recalibrate")))
            recal_btn.set_child(btn_content)
            recal_btn.add_css_class("suggested-action")
            recal_btn.connect("clicked", lambda b: self._on_recalibrate())
            header.append(recal_btn)

        main_box.append(header)
        main_box.append(Gtk.Separator())

        # ---- Warning mode ----
        warn_label = Gtk.Label(label=_("Warning mode"))
        warn_label.add_css_class("heading")
        warn_label.set_halign(Gtk.Align.START)
        main_box.append(warn_label)

        mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        mode_box.add_css_class("linked")
        self._mode_buttons: list[Gtk.ToggleButton] = []
        modes = [
            (_("Glow"), WarningMode.GLOW),
            (_("Border"), WarningMode.BORDER),
            (_("Solid"), WarningMode.SOLID),
            (_("None"), WarningMode.NONE),
        ]
        for label, mode in modes:
            btn = Gtk.ToggleButton(label=label)
            btn.set_active(settings.warning_mode == mode)
            btn._dorso_mode = mode
            btn.connect("toggled", self._on_mode_toggled)
            mode_box.append(btn)
            self._mode_buttons.append(btn)
        mode_row.append(mode_box)

        # Color picker
        r, g, b = settings.warning_color
        rgba = Gdk.RGBA()
        rgba.red, rgba.green, rgba.blue, rgba.alpha = r, g, b, 1.0
        color_dialog = Gtk.ColorDialog()
        color_dialog.set_with_alpha(False)
        self._color_btn = Gtk.ColorDialogButton(dialog=color_dialog)
        self._color_btn.set_rgba(rgba)
        self._color_btn.connect("notify::rgba", self._on_color_changed)
        mode_row.append(self._color_btn)

        main_box.append(mode_row)

        # ---- Sliders ----
        main_box.append(Gtk.Separator())
        sliders_label = Gtk.Label(label=_("Settings"))
        sliders_label.add_css_class("heading")
        sliders_label.set_halign(Gtk.Align.START)
        main_box.append(sliders_label)

        self._intensity_scale, self._intensity_vlabel = self._add_slider_row(
            main_box, _("Intensity"), 0.1, 3.0, 0.1, settings.intensity,
            lambda v: _("Gentle") if v < 0.8 else _("Strong") if v > 1.5 else _("Medium")
        )
        self._sensitivity_scale, self._sensitivity_vlabel = self._add_slider_row(
            main_box, _("Sensitivity"), 0.01, 0.10, 0.005, settings.slouch_sensitivity,
            lambda v: _("High") if v < 0.03 else _("Low") if v > 0.06 else _("Medium")
        )
        self._delay_scale, self._delay_vlabel = self._add_slider_row(
            main_box, _("Warning delay"), 0.0, 5.0, 0.5, settings.warning_onset_delay,
            lambda v: f"{v:.0f}s"
        )

        # ---- Detection mode ----
        main_box.append(Gtk.Separator())
        det_label = Gtk.Label(label=_("Detection speed"))
        det_label.add_css_class("heading")
        det_label.set_halign(Gtk.Align.START)
        main_box.append(det_label)

        det_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        det_box.add_css_class("linked")
        self._det_buttons: list[Gtk.ToggleButton] = []
        det_modes = [
            (_("Responsive"), DetectionMode.RESPONSIVE),
            (_("Balanced"), DetectionMode.BALANCED),
            (_("Eco"), DetectionMode.PERFORMANCE),
        ]
        for label, mode in det_modes:
            btn = Gtk.ToggleButton(label=label)
            btn.set_active(settings.detection_mode == mode)
            btn._dorso_mode = mode
            btn.connect("toggled", self._on_det_toggled)
            det_box.append(btn)
            self._det_buttons.append(btn)
        main_box.append(det_box)

        # ---- Camera ----
        main_box.append(Gtk.Separator())
        cam_heading = Gtk.Label(label=_("Camera"))
        cam_heading.add_css_class("heading")
        cam_heading.set_halign(Gtk.Align.START)
        main_box.append(cam_heading)

        cam_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self._camera_dropdown = Gtk.DropDown()
        self._camera_dropdown.set_hexpand(True)
        self._camera_map: list[int] = []
        self._populate_camera_dropdown(settings.camera_id)
        self._camera_dropdown.connect("notify::selected", self._on_camera_changed)
        cam_row.append(self._camera_dropdown)

        refresh_btn = Gtk.Button()
        refresh_btn.set_child(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
        refresh_btn.set_tooltip_text(_("Refresh camera list"))
        refresh_btn.connect("clicked", lambda b: self._populate_camera_dropdown(
            self._camera_map[self._camera_dropdown.get_selected()]
            if self._camera_dropdown.get_selected() < len(self._camera_map)
            else self._settings.camera_id
        ))
        cam_row.append(refresh_btn)

        main_box.append(cam_row)

        # Camera preview
        frame = Gtk.Frame()
        self._cam_preview = Gtk.Picture()
        self._cam_preview.set_size_request(200, 150)
        self._cam_preview.set_content_fit(Gtk.ContentFit.CONTAIN)
        frame.set_child(self._cam_preview)
        frame.set_halign(Gtk.Align.CENTER)
        self._cam_preview_frame = frame
        frame.set_visible(False)
        main_box.append(frame)

        # Start preview via hub
        if self._camera_map:
            self._start_camera_preview()

        # ---- Autostart ----
        main_box.append(Gtk.Separator())
        autostart_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        autostart_label = Gtk.Label(label=_("Launch at startup"))
        autostart_label.set_hexpand(True)
        autostart_label.set_halign(Gtk.Align.START)
        autostart_row.append(autostart_label)
        self._autostart_switch = Gtk.Switch()
        self._autostart_switch.set_active(_autostart_path().exists())
        self._autostart_switch.set_valign(Gtk.Align.CENTER)
        self._autostart_switch.connect("notify::active", self._on_autostart_toggled)
        autostart_row.append(self._autostart_switch)
        main_box.append(autostart_row)

        # ---- Calibration info ----
        if settings.calibration and settings.calibration.is_valid:
            main_box.append(Gtk.Separator())
            cal_label = Gtk.Label()
            cal_label.set_markup(
                f"<small>Calibration : nez_y = {settings.calibration.nose_y:.3f}, "
                f"visage = {settings.calibration.face_width:.3f}</small>"
            )
            cal_label.set_halign(Gtk.Align.START)
            cal_label.add_css_class("dim-label")
            main_box.append(cal_label)

        scroll.set_child(main_box)
        self._window.set_child(scroll)
        self._window.connect("close-request", self._on_close)

    def show(self) -> None:
        self._window.set_visible(True)

    def _on_close(self, window: Gtk.Window) -> bool:
        self._stop_camera_preview()
        if self._on_close_cb:
            self._on_close_cb()
        return False

    def _add_slider_row(
        self, parent: Gtk.Box, label: str,
        min_v: float, max_v: float, step: float, value: float,
        fmt_fn,
    ) -> tuple[Gtk.Scale, Gtk.Label]:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        lbl = Gtk.Label(label=label)
        lbl.set_halign(Gtk.Align.START)
        lbl.set_size_request(120, -1)
        row.append(lbl)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, min_v, max_v, step)
        scale.set_value(value)
        scale.set_hexpand(True)
        scale.set_draw_value(False)
        scale.connect("value-changed", self._on_value_changed)
        row.append(scale)

        val_label = Gtk.Label(label=fmt_fn(value))
        val_label.set_size_request(50, -1)
        val_label.set_halign(Gtk.Align.END)
        val_label.add_css_class("accent")
        row.append(val_label)

        scale._dorso_fmt = fmt_fn
        scale._dorso_label = val_label

        parent.append(row)
        return scale, val_label

    def _populate_camera_dropdown(self, current_id: int) -> None:
        """Scan V4L2 devices and rebuild the dropdown model."""
        self._updating = True
        cameras = list_cameras()

        labels: list[str] = []
        self._camera_map = []
        selected_pos = 0

        if cameras:
            for i, (dev_id, name) in enumerate(cameras):
                labels.append(name)
                self._camera_map.append(dev_id)
                if dev_id == current_id:
                    selected_pos = i
            # If saved camera_id was not found, add it as unavailable
            if current_id not in self._camera_map:
                labels.append(_("Camera %d (unavailable)") % current_id)
                self._camera_map.append(current_id)
                selected_pos = len(labels) - 1
        else:
            labels.append(_("No camera detected"))
            self._camera_map.append(current_id)

        model = Gtk.StringList.new(labels)
        self._camera_dropdown.set_model(model)
        self._camera_dropdown.set_selected(selected_pos)
        self._updating = False

    def _on_camera_changed(self, dropdown, pspec) -> None:
        if self._updating:
            return
        selected = self._camera_dropdown.get_selected()
        if selected < len(self._camera_map):
            new_dev = f"/dev/video{self._camera_map[selected]}"
            self._hub.set_device(new_dev)
        self._apply()

    # -- Camera preview via hub --

    def _start_camera_preview(self) -> None:
        """Subscribe to hub for live preview frames."""
        self._stop_camera_preview()
        self._cam_preview_frame.set_visible(True)
        self._preview_subscribed = True
        self._hub.subscribe("settings_preview", self._on_preview_frame, fps=10.0)

    def _stop_camera_preview(self) -> None:
        if self._preview_subscribed:
            self._hub.unsubscribe("settings_preview")
            self._preview_subscribed = False

    def _on_preview_frame(self, frame) -> None:
        """Called from hub thread — flip, convert, dispatch to GTK."""
        import cv2

        frame = cv2.flip(frame, 1)
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
            self._cam_preview.set_paintable(texture)
        except Exception:
            pass
        return False

    def _on_mode_toggled(self, btn: Gtk.ToggleButton) -> None:
        if self._updating:
            return
        if not btn.get_active():
            return
        self._updating = True
        for b in self._mode_buttons:
            if b is not btn:
                b.set_active(False)
        self._updating = False
        self._apply()

    def _on_det_toggled(self, btn: Gtk.ToggleButton) -> None:
        if self._updating:
            return
        if not btn.get_active():
            return
        self._updating = True
        for b in self._det_buttons:
            if b is not btn:
                b.set_active(False)
        self._updating = False
        self._apply()

    def _on_autostart_toggled(self, switch, pspec) -> None:
        dst = _autostart_path()
        if switch.get_active():
            src = _desktop_source()
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        else:
            dst.unlink(missing_ok=True)

    def _on_color_changed(self, btn, pspec) -> None:
        self._apply()

    def _on_value_changed(self, widget) -> None:
        for scale in [self._intensity_scale, self._sensitivity_scale, self._delay_scale]:
            if hasattr(scale, '_dorso_fmt'):
                scale._dorso_label.set_text(scale._dorso_fmt(scale.get_value()))
        self._apply()

    def _apply(self) -> None:
        for btn in self._mode_buttons:
            if btn.get_active():
                self._settings.warning_mode = btn._dorso_mode
                break
        for btn in self._det_buttons:
            if btn.get_active():
                self._settings.detection_mode = btn._dorso_mode
                break
        self._settings.intensity = round(self._intensity_scale.get_value(), 2)
        self._settings.slouch_sensitivity = round(self._sensitivity_scale.get_value(), 3)
        self._settings.warning_onset_delay = round(self._delay_scale.get_value(), 1)
        selected = self._camera_dropdown.get_selected()
        if selected < len(self._camera_map):
            self._settings.camera_id = self._camera_map[selected]
        rgba = self._color_btn.get_rgba()
        self._settings.warning_color = (
            round(rgba.red, 3), round(rgba.green, 3), round(rgba.blue, 3)
        )
        self._settings.save()
        self._on_changed(self._settings)
