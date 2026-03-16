"""Screen overlay for visual posture warnings.

Strategy by display server:
- Wayland + Layer Shell (Sway, Hyprland, etc.): proper overlay layer with cairo alpha
- Wayland + GNOME: fullscreen window with compositor-level opacity
- X11: fullscreen transparent window with input passthrough via XShape
"""

from __future__ import annotations

import logging
import math
import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from dorso.models import WarningMode

logger = logging.getLogger(__name__)

# Try to load gtk4-layer-shell for Wayland support
_layer_shell_available = False
try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell

    _layer_shell_available = True
except (ValueError, ImportError):
    pass

# Warning color (red tint)
WARNING_COLOR = (0.9, 0.2, 0.1)


def _is_wayland() -> bool:
    return "WAYLAND_DISPLAY" in os.environ


class OverlayWindow(Gtk.Window):
    """A single fullscreen overlay for one monitor."""

    def __init__(self, monitor: Gdk.Monitor) -> None:
        super().__init__()
        self._monitor = monitor
        self._intensity = 0.0
        self._warning_mode = WarningMode.GLOW
        self._layer_shell_ok = False

        self.set_decorated(False)
        self.set_can_focus(False)

        # Drawing area fills the window
        self._drawing_area = Gtk.DrawingArea()
        self._drawing_area.set_draw_func(self._on_draw)
        self.set_child(self._drawing_area)

        # Set empty input region so all input passes through
        self.connect("realize", self._set_passthrough)

        self._setup_platform()

    def _setup_platform(self) -> None:
        """Configure platform-specific overlay behavior."""
        if _layer_shell_available and _is_wayland() and Gtk4LayerShell.is_supported():
            self._try_layer_shell()

        if not self._layer_shell_ok:
            self._setup_generic()

    def _try_layer_shell(self) -> None:
        """Set up as a Wayland layer-shell overlay (Sway, Hyprland, etc.)."""
        try:
            Gtk4LayerShell.init_for_window(self)
            Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.OVERLAY)
            Gtk4LayerShell.set_monitor(self, self._monitor)
            Gtk4LayerShell.set_exclusive_zone(self, -1)
            for edge in (
                Gtk4LayerShell.Edge.TOP,
                Gtk4LayerShell.Edge.BOTTOM,
                Gtk4LayerShell.Edge.LEFT,
                Gtk4LayerShell.Edge.RIGHT,
            ):
                Gtk4LayerShell.set_anchor(self, edge, True)
            Gtk4LayerShell.set_keyboard_mode(
                self, Gtk4LayerShell.KeyboardMode.NONE
            )
            # Layer shell + CSS transparency = proper alpha overlay
            self._setup_transparent_css()
            self._layer_shell_ok = True
            logger.info("Overlay using Wayland Layer Shell")
        except Exception as e:
            logger.debug("Layer Shell init failed: %s", e)

    def _setup_transparent_css(self) -> None:
        """Apply CSS to make window background transparent (for layer-shell/X11)."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string(
            "window.dorso-overlay, window.dorso-overlay > * "
            "{ background: none; background-color: transparent; }"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self.add_css_class("dorso-overlay")

    def _set_passthrough(self, widget: Gtk.Widget) -> None:
        """Set empty input region so all clicks/keys pass through."""
        import cairo as _cairo

        surface = self.get_surface()
        if surface:
            surface.set_input_region(_cairo.Region())
            logger.debug("Input passthrough enabled")

    def _setup_generic(self) -> None:
        """Generic overlay for GNOME Wayland and X11.

        On GNOME Wayland, fullscreen() forces an opaque background.
        Using maximize() instead preserves per-pixel alpha transparency.
        """
        geo = self._monitor.get_geometry()
        self.set_default_size(geo.width, geo.height)
        self._setup_transparent_css()
        logger.info("Overlay using transparent maximized window (%dx%d)", geo.width, geo.height)

    def set_intensity(self, intensity: float) -> None:
        """Set warning intensity (0.0 = hidden, 1.0 = maximum)."""
        self._intensity = max(0.0, min(1.0, intensity))

        if self._intensity > 0:
            if not self.get_visible():
                self.set_visible(True)
                if not self._layer_shell_ok:
                    self.maximize()
            self._drawing_area.queue_draw()
        else:
            self.set_visible(False)

    def set_warning_mode(self, mode: WarningMode) -> None:
        self._warning_mode = mode
        if self._intensity > 0:
            self._drawing_area.queue_draw()

    def _on_draw(
        self,
        area: Gtk.DrawingArea,
        cr: object,  # cairo.Context
        width: int,
        height: int,
    ) -> None:
        """Draw the warning overlay with per-pixel alpha."""
        import cairo

        # Clear to fully transparent
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        if self._intensity <= 0:
            return

        r, g, b = WARNING_COLOR
        if self._warning_mode == WarningMode.SOLID:
            self._draw_solid(cr, width, height, r, g, b)
        elif self._warning_mode == WarningMode.BORDER:
            self._draw_border(cr, width, height, r, g, b)
        else:  # GLOW
            self._draw_glow(cr, width, height, r, g, b)

    # -- Per-pixel alpha drawing (layer shell / X11) --

    def _draw_solid(self, cr, w: int, h: int, r: float, g: float, b: float) -> None:
        cr.set_source_rgba(r, g, b, self._intensity * 0.4)
        cr.rectangle(0, 0, w, h)
        cr.fill()

    def _draw_border(self, cr, w: int, h: int, r: float, g: float, b: float) -> None:
        border_size = int(min(w, h) * 0.08 * self._intensity)
        if border_size < 1:
            return
        alpha = self._intensity * 0.7
        self._draw_gradient_rect(cr, 0, 0, w, border_size, r, g, b, alpha, "down")
        self._draw_gradient_rect(cr, 0, h - border_size, w, border_size, r, g, b, alpha, "up")
        self._draw_gradient_rect(cr, 0, 0, border_size, h, r, g, b, alpha, "right")
        self._draw_gradient_rect(cr, w - border_size, 0, border_size, h, r, g, b, alpha, "left")

    def _draw_glow(self, cr, w: int, h: int, r: float, g: float, b: float) -> None:
        import cairo

        cx, cy = w / 2, h / 2
        max_radius = math.sqrt(cx * cx + cy * cy)
        inner_radius = max_radius * (1.0 - self._intensity * 0.6)

        pattern = cairo.RadialGradient(cx, cy, inner_radius, cx, cy, max_radius)
        pattern.add_color_stop_rgba(0, r, g, b, 0.0)
        pattern.add_color_stop_rgba(1, r, g, b, self._intensity * 0.6)

        cr.set_source(pattern)
        cr.rectangle(0, 0, w, h)
        cr.fill()

    @staticmethod
    def _draw_gradient_rect(
        cr, x: int, y: int, w: int, h: int,
        r: float, g: float, b: float, alpha: float,
        direction: str,
    ) -> None:
        import cairo

        if direction == "down":
            pattern = cairo.LinearGradient(x, y, x, y + h)
        elif direction == "up":
            pattern = cairo.LinearGradient(x, y + h, x, y)
        elif direction == "right":
            pattern = cairo.LinearGradient(x, y, x + w, y)
        else:
            pattern = cairo.LinearGradient(x + w, y, x, y)

        pattern.add_color_stop_rgba(0, r, g, b, alpha)
        pattern.add_color_stop_rgba(1, r, g, b, 0.0)

        cr.set_source(pattern)
        cr.rectangle(x, y, w, h)
        cr.fill()


class OverlayManager:
    """Manages overlay windows across all monitors."""

    def __init__(self) -> None:
        self._overlays: list[OverlayWindow] = []
        self._warning_mode = WarningMode.GLOW
        self._available = False

    def setup(self) -> None:
        """Create overlay windows for all monitors."""
        display = Gdk.Display.get_default()
        if display is None:
            logger.error("No display available")
            return

        monitors = display.get_monitors()
        n = monitors.get_n_items()
        logger.info("Setting up overlays for %d monitor(s)", n)
        for i in range(n):
            monitor = monitors.get_item(i)
            try:
                overlay = OverlayWindow(monitor)
                overlay.set_warning_mode(self._warning_mode)
                self._overlays.append(overlay)
            except Exception as e:
                logger.warning("Failed to create overlay for monitor %d: %s", i, e)

        self._available = len(self._overlays) > 0

    @property
    def available(self) -> bool:
        return self._available

    def set_intensity(self, intensity: float) -> None:
        for overlay in self._overlays:
            overlay.set_intensity(intensity)

    def set_warning_mode(self, mode: WarningMode) -> None:
        self._warning_mode = mode
        for overlay in self._overlays:
            overlay.set_warning_mode(mode)

    def clear(self) -> None:
        self.set_intensity(0.0)

    def destroy(self) -> None:
        for overlay in self._overlays:
            overlay.destroy()
        self._overlays.clear()
