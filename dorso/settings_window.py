"""Settings window — polished GTK4 dialog inspired by dorso macOS."""

from __future__ import annotations

import logging
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

from dorso.models import DetectionMode, WarningMode
from dorso.settings import Settings

logger = logging.getLogger(__name__)

# Accent color matching dorso macOS (teal)
_CSS = """
.dorso-settings {
    background-color: #f5f6f8;
}
.dorso-card {
    background-color: #ffffff;
    border-radius: 12px;
    padding: 16px;
}
.dorso-section-title {
    font-weight: bold;
    font-size: 13px;
    color: #2e3340;
}
.dorso-label {
    color: #8c919a;
    font-size: 12px;
}
.dorso-value-label {
    color: #3cbdb5;
    font-weight: bold;
    font-size: 12px;
}
.dorso-mode-btn {
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 12px;
    background-color: #e8eaed;
    color: #2e3340;
    border: none;
    min-height: 28px;
}
.dorso-mode-btn:checked,
.dorso-mode-btn-active {
    background-color: #3cbdb5;
    color: white;
}
.dorso-accent-btn {
    background-color: #3cbdb5;
    color: white;
    border-radius: 8px;
    padding: 6px 16px;
    font-weight: bold;
    border: none;
    min-height: 28px;
}
.dorso-accent-btn:hover {
    background-color: #35a9a2;
}
.dorso-header {
    background-color: #ffffff;
    border-radius: 12px;
    padding: 12px 16px;
}
"""


class SettingsWindow:
    """Polished settings dialog."""

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

        # Apply CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string(_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self._window = Gtk.Window(title="Dorso — Paramètres")
        self._window.set_default_size(460, 530)
        self._window.set_resizable(False)
        self._window.add_css_class("dorso-settings")

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.set_margin_top(16)
        main_box.set_margin_bottom(16)
        main_box.set_margin_start(16)
        main_box.set_margin_end(16)

        # ---- Header card ----
        header = self._make_card()
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label="Dorso")
        title.set_halign(Gtk.Align.START)
        title.add_css_class("dorso-section-title")
        title.set_markup("<span size='large' weight='bold'>Dorso</span>")
        title_box.append(title)

        ver = Gtk.Label(label="v0.1.0 — Linux")
        ver.set_halign(Gtk.Align.START)
        ver.add_css_class("dorso-label")
        title_box.append(ver)

        header_box.append(title_box)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header_box.append(spacer)

        if self._on_recalibrate:
            recal_btn = Gtk.Button()
            recal_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            recal_icon = Gtk.Label(label="↻")
            recal_icon.set_markup("<span size='large'>↻</span>")
            recal_btn_box.append(recal_icon)
            recal_btn_box.append(Gtk.Label(label="Recalibrer"))
            recal_btn.set_child(recal_btn_box)
            recal_btn.add_css_class("dorso-accent-btn")
            recal_btn.connect("clicked", lambda b: self._on_recalibrate())
            header_box.append(recal_btn)

        header.append(header_box)
        main_box.append(header)

        # ---- Warning mode card ----
        warn_card = self._make_card()

        warn_title = Gtk.Label()
        warn_title.set_markup("<b>Alerte</b>")
        warn_title.set_halign(Gtk.Align.START)
        warn_card.append(warn_title)

        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        mode_box.set_margin_top(8)
        self._mode_buttons: list[Gtk.ToggleButton] = []
        modes = [
            ("Glow", WarningMode.GLOW),
            ("Bordures", WarningMode.BORDER),
            ("Solide", WarningMode.SOLID),
            ("Aucun", WarningMode.NONE),
        ]
        for label, mode in modes:
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("dorso-mode-btn")
            btn.set_active(settings.warning_mode == mode)
            btn._dorso_mode = mode
            btn.connect("toggled", self._on_mode_toggled)
            mode_box.append(btn)
            self._mode_buttons.append(btn)
        warn_card.append(mode_box)
        main_box.append(warn_card)

        # ---- Sliders card ----
        sliders_card = self._make_card()

        sliders_title = Gtk.Label()
        sliders_title.set_markup("<b>Réglages</b>")
        sliders_title.set_halign(Gtk.Align.START)
        sliders_card.append(sliders_title)

        self._intensity_scale, self._intensity_label = self._add_slider_row(
            sliders_card, "Intensité", 0.1, 3.0, 0.1, settings.intensity,
            lambda v: "Doux" if v < 0.8 else "Fort" if v > 1.5 else "Moyen"
        )
        self._sensitivity_scale, self._sensitivity_label = self._add_slider_row(
            sliders_card, "Sensibilité", 0.01, 0.10, 0.005, settings.slouch_sensitivity,
            lambda v: "Haute" if v < 0.03 else "Basse" if v > 0.06 else "Moyenne"
        )
        self._delay_scale, self._delay_label = self._add_slider_row(
            sliders_card, "Délai", 0.0, 5.0, 0.5, settings.warning_onset_delay,
            lambda v: f"{v:.0f}s"
        )
        main_box.append(sliders_card)

        # ---- Detection card ----
        det_card = self._make_card()

        det_title = Gtk.Label()
        det_title.set_markup("<b>Détection</b>")
        det_title.set_halign(Gtk.Align.START)
        det_card.append(det_title)

        det_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        det_box.set_margin_top(8)
        self._det_buttons: list[Gtk.ToggleButton] = []
        det_modes = [
            ("Réactif", DetectionMode.RESPONSIVE),
            ("Équilibré", DetectionMode.BALANCED),
            ("Éco", DetectionMode.PERFORMANCE),
        ]
        for label, mode in det_modes:
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("dorso-mode-btn")
            btn.set_active(settings.detection_mode == mode)
            btn._dorso_mode = mode
            btn.connect("toggled", self._on_det_toggled)
            det_box.append(btn)
            self._det_buttons.append(btn)
        det_card.append(det_box)

        # Camera ID
        cam_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cam_row.set_margin_top(12)
        cam_label = Gtk.Label(label="Caméra")
        cam_label.set_halign(Gtk.Align.START)
        cam_label.set_hexpand(True)
        cam_label.add_css_class("dorso-label")
        cam_row.append(cam_label)
        self._camera_spin = Gtk.SpinButton.new_with_range(0, 10, 1)
        self._camera_spin.set_value(settings.camera_id)
        self._camera_spin.connect("value-changed", self._on_value_changed)
        cam_row.append(self._camera_spin)
        det_card.append(cam_row)

        main_box.append(det_card)

        # ---- Calibration info ----
        if settings.calibration and settings.calibration.is_valid:
            info_card = self._make_card()
            cal_label = Gtk.Label()
            cal_label.set_markup(
                f"<small>Calibration: nez_y = {settings.calibration.nose_y:.3f}, "
                f"visage = {settings.calibration.face_width:.3f}</small>"
            )
            cal_label.set_halign(Gtk.Align.START)
            cal_label.add_css_class("dorso-label")
            info_card.append(cal_label)
            main_box.append(info_card)

        scroll.set_child(main_box)
        self._window.set_child(scroll)

    def show(self) -> None:
        self._window.set_visible(True)

    def _make_card(self) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class("dorso-card")
        card.set_margin_start(0)
        card.set_margin_end(0)
        return card

    def _add_slider_row(
        self, parent: Gtk.Box, label: str,
        min_v: float, max_v: float, step: float, value: float,
        fmt_fn,
    ) -> tuple[Gtk.Scale, Gtk.Label]:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_top(10)

        lbl = Gtk.Label(label=label)
        lbl.set_halign(Gtk.Align.START)
        lbl.set_size_request(80, -1)
        lbl.add_css_class("dorso-label")
        row.append(lbl)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, min_v, max_v, step)
        scale.set_value(value)
        scale.set_hexpand(True)
        scale.set_draw_value(False)
        scale.connect("value-changed", self._on_value_changed)
        row.append(scale)

        val_label = Gtk.Label(label=fmt_fn(value))
        val_label.set_size_request(60, -1)
        val_label.set_halign(Gtk.Align.END)
        val_label.add_css_class("dorso-value-label")
        row.append(val_label)

        # Store format function on scale for updates
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

    def _on_value_changed(self, widget) -> None:
        # Update value labels
        for scale in [self._intensity_scale, self._sensitivity_scale, self._delay_scale]:
            if hasattr(scale, '_dorso_fmt'):
                scale._dorso_label.set_text(scale._dorso_fmt(scale.get_value()))
        self._apply()

    def _apply(self) -> None:
        # Warning mode
        for btn in self._mode_buttons:
            if btn.get_active():
                self._settings.warning_mode = btn._dorso_mode
                break

        # Detection mode
        for btn in self._det_buttons:
            if btn.get_active():
                self._settings.detection_mode = btn._dorso_mode
                break

        self._settings.intensity = round(self._intensity_scale.get_value(), 2)
        self._settings.slouch_sensitivity = round(self._sensitivity_scale.get_value(), 3)
        self._settings.warning_onset_delay = round(self._delay_scale.get_value(), 1)
        self._settings.camera_id = int(self._camera_spin.get_value())
        self._settings.save()
        self._on_changed(self._settings)
