"""Settings window — GTK4 dialog for adjusting dorso parameters."""

from __future__ import annotations

import logging
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from dorso.models import DetectionMode, WarningMode
from dorso.settings import Settings

logger = logging.getLogger(__name__)


class SettingsWindow:
    """GTK4 settings dialog."""

    def __init__(
        self,
        settings: Settings,
        on_changed: Callable[[Settings], None],
    ) -> None:
        self._settings = settings
        self._on_changed = on_changed

        self._window = Gtk.Window(title="Dorso — Paramètres")
        self._window.set_default_size(420, 480)
        self._window.set_resizable(False)

        # Main layout
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)

        # -- Warning mode --
        box.append(self._make_section("Feedback visuel"))

        mode_box = self._make_row("Mode d'alerte")
        self._warning_mode = Gtk.DropDown.new_from_strings(["Glow", "Bordures", "Solide", "Aucun"])
        mode_idx = {WarningMode.GLOW: 0, WarningMode.BORDER: 1, WarningMode.SOLID: 2, WarningMode.NONE: 3}
        self._warning_mode.set_selected(mode_idx.get(settings.warning_mode, 0))
        self._warning_mode.connect("notify::selected", self._on_warning_mode_changed)
        mode_box.append(self._warning_mode)
        box.append(mode_box)

        # -- Intensity --
        row, self._intensity = self._make_scale_row("Intensité", 0.1, 3.0, 0.1, settings.intensity)
        self._intensity.connect("value-changed", self._on_value_changed)
        box.append(row)

        # -- Sensitivity --
        row, self._sensitivity = self._make_scale_row("Sensibilité", 0.01, 0.10, 0.005, settings.slouch_sensitivity)
        self._sensitivity.connect("value-changed", self._on_value_changed)
        box.append(row)

        # -- Onset delay --
        row, self._onset_delay = self._make_scale_row("Délai avant alerte (s)", 0.0, 5.0, 0.5, settings.warning_onset_delay)
        self._onset_delay.connect("value-changed", self._on_value_changed)
        box.append(row)

        # -- Detection mode --
        box.append(self._make_section("Performance"))

        det_box = self._make_row("Mode de détection")
        self._detection_mode = Gtk.DropDown.new_from_strings(["Réactif (~10 fps)", "Équilibré (~4 fps)", "Économique (~2 fps)"])
        det_idx = {DetectionMode.RESPONSIVE: 0, DetectionMode.BALANCED: 1, DetectionMode.PERFORMANCE: 2}
        self._detection_mode.set_selected(det_idx.get(settings.detection_mode, 0))
        self._detection_mode.connect("notify::selected", self._on_detection_mode_changed)
        det_box.append(self._detection_mode)
        box.append(det_box)

        # -- Camera --
        box.append(self._make_section("Caméra"))

        cam_box = self._make_row("ID caméra")
        self._camera_id = Gtk.SpinButton.new_with_range(0, 10, 1)
        self._camera_id.set_value(settings.camera_id)
        self._camera_id.connect("value-changed", self._on_value_changed)
        cam_box.append(self._camera_id)
        box.append(cam_box)

        # -- Calibration info --
        if settings.calibration and settings.calibration.is_valid:
            cal_label = Gtk.Label()
            cal_label.set_markup(
                f"<small>Calibration : nez_y={settings.calibration.nose_y:.3f}, "
                f"visage={settings.calibration.face_width:.3f}</small>"
            )
            cal_label.set_halign(Gtk.Align.START)
            cal_label.add_css_class("dim-label")
            box.append(cal_label)

        scroll.set_child(box)
        self._window.set_child(scroll)

    def show(self) -> None:
        self._window.set_visible(True)

    def _apply(self) -> None:
        """Gather values and notify callback."""
        mode_map = {0: WarningMode.GLOW, 1: WarningMode.BORDER, 2: WarningMode.SOLID, 3: WarningMode.NONE}
        det_map = {0: DetectionMode.RESPONSIVE, 1: DetectionMode.BALANCED, 2: DetectionMode.PERFORMANCE}

        self._settings.warning_mode = mode_map.get(self._warning_mode.get_selected(), WarningMode.GLOW)
        self._settings.detection_mode = det_map.get(self._detection_mode.get_selected(), DetectionMode.RESPONSIVE)
        self._settings.intensity = round(self._intensity.get_value(), 2)
        self._settings.slouch_sensitivity = round(self._sensitivity.get_value(), 3)
        self._settings.warning_onset_delay = round(self._onset_delay.get_value(), 1)
        self._settings.camera_id = int(self._camera_id.get_value())
        self._settings.save()
        self._on_changed(self._settings)

    def _on_warning_mode_changed(self, dropdown, _pspec) -> None:
        self._apply()

    def _on_detection_mode_changed(self, dropdown, _pspec) -> None:
        self._apply()

    def _on_value_changed(self, widget) -> None:
        self._apply()

    @staticmethod
    def _make_section(title: str) -> Gtk.Label:
        label = Gtk.Label()
        label.set_markup(f"<b>{title}</b>")
        label.set_halign(Gtk.Align.START)
        label.set_margin_top(8)
        return label

    @staticmethod
    def _make_row(label_text: str) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        label = Gtk.Label(label=label_text)
        label.set_halign(Gtk.Align.START)
        label.set_hexpand(True)
        row.append(label)
        return row

    @staticmethod
    def _make_scale_row(
        label_text: str, min_val: float, max_val: float, step: float, value: float
    ) -> tuple[Gtk.Box, Gtk.Scale]:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        label = Gtk.Label(label=label_text)
        label.set_halign(Gtk.Align.START)
        label.set_hexpand(True)
        row.append(label)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, min_val, max_val, step)
        scale.set_value(value)
        scale.set_size_request(180, -1)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        row.append(scale)
        return row, scale
