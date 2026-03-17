"""Settings window — GTK4 dialog using native Adwaita/GNOME styling."""

from __future__ import annotations

import logging
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

from dorso.models import DetectionMode, WarningMode
from dorso.settings import Settings

logger = logging.getLogger(__name__)


class SettingsWindow:
    """Settings dialog using native GTK4/Adwaita CSS classes."""

    def __init__(
        self,
        settings: Settings,
        on_changed: Callable[[Settings], None],
        on_recalibrate: Callable[[], None] | None = None,
    ) -> None:
        self._settings = settings
        self._on_changed = on_changed
        self._on_recalibrate = on_recalibrate
        self._updating = False

        self._window = Gtk.Window(title="Dorso — Paramètres")
        self._window.set_default_size(440, 520)
        self._window.set_resizable(False)

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
            btn_content.append(Gtk.Label(label="Recalibrer"))
            recal_btn.set_child(btn_content)
            recal_btn.add_css_class("suggested-action")
            recal_btn.connect("clicked", lambda b: self._on_recalibrate())
            header.append(recal_btn)

        main_box.append(header)
        main_box.append(Gtk.Separator())

        # ---- Warning mode ----
        warn_label = Gtk.Label(label="Mode d'alerte")
        warn_label.add_css_class("heading")
        warn_label.set_halign(Gtk.Align.START)
        main_box.append(warn_label)

        mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        mode_box.add_css_class("linked")
        self._mode_buttons: list[Gtk.ToggleButton] = []
        modes = [
            ("Glow", WarningMode.GLOW),
            ("Bordures", WarningMode.BORDER),
            ("Solide", WarningMode.SOLID),
            ("Aucun", WarningMode.NONE),
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
        sliders_label = Gtk.Label(label="Réglages")
        sliders_label.add_css_class("heading")
        sliders_label.set_halign(Gtk.Align.START)
        main_box.append(sliders_label)

        self._intensity_scale, self._intensity_vlabel = self._add_slider_row(
            main_box, "Intensité", 0.1, 3.0, 0.1, settings.intensity,
            lambda v: "Doux" if v < 0.8 else "Fort" if v > 1.5 else "Moyen"
        )
        self._sensitivity_scale, self._sensitivity_vlabel = self._add_slider_row(
            main_box, "Sensibilité", 0.01, 0.10, 0.005, settings.slouch_sensitivity,
            lambda v: "Haute" if v < 0.03 else "Basse" if v > 0.06 else "Moyenne"
        )
        self._delay_scale, self._delay_vlabel = self._add_slider_row(
            main_box, "Délai avant alerte", 0.0, 5.0, 0.5, settings.warning_onset_delay,
            lambda v: f"{v:.0f}s"
        )

        # ---- Detection mode ----
        main_box.append(Gtk.Separator())
        det_label = Gtk.Label(label="Vitesse de détection")
        det_label.add_css_class("heading")
        det_label.set_halign(Gtk.Align.START)
        main_box.append(det_label)

        det_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        det_box.add_css_class("linked")
        self._det_buttons: list[Gtk.ToggleButton] = []
        det_modes = [
            ("Réactif", DetectionMode.RESPONSIVE),
            ("Équilibré", DetectionMode.BALANCED),
            ("Éco", DetectionMode.PERFORMANCE),
        ]
        for label, mode in det_modes:
            btn = Gtk.ToggleButton(label=label)
            btn.set_active(settings.detection_mode == mode)
            btn._dorso_mode = mode
            btn.connect("toggled", self._on_det_toggled)
            det_box.append(btn)
            self._det_buttons.append(btn)
        main_box.append(det_box)

        # Camera ID
        cam_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cam_row.set_margin_top(8)
        cam_label = Gtk.Label(label="Caméra")
        cam_label.set_hexpand(True)
        cam_label.set_halign(Gtk.Align.START)
        cam_row.append(cam_label)
        self._camera_spin = Gtk.SpinButton.new_with_range(0, 10, 1)
        self._camera_spin.set_value(settings.camera_id)
        self._camera_spin.connect("value-changed", self._on_value_changed)
        cam_row.append(self._camera_spin)
        main_box.append(cam_row)

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

    def show(self) -> None:
        self._window.set_visible(True)

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
        self._settings.camera_id = int(self._camera_spin.get_value())
        rgba = self._color_btn.get_rgba()
        self._settings.warning_color = (
            round(rgba.red, 3), round(rgba.green, 3), round(rgba.blue, 3)
        )
        self._settings.save()
        self._on_changed(self._settings)
