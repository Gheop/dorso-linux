"""Screen overlay for visual posture warnings.

Multi-monitor strategy:
- Layer Shell (Sway, Hyprland): one overlay window per monitor (compositor handles placement)
- GNOME Wayland / X11: one maximized transparent window spanning the full desktop,
  with effects drawn per-monitor region
"""

from __future__ import annotations

import logging
import math
import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk

from dorso.models import WarningMode

logger = logging.getLogger(__name__)

_layer_shell_available = False
try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell

    _layer_shell_available = True
except (ValueError, ImportError):
    pass

WARNING_COLOR = (0.9, 0.2, 0.1)


def _is_wayland() -> bool:
    return "WAYLAND_DISPLAY" in os.environ


def _use_layer_shell() -> bool:
    return _layer_shell_available and _is_wayland() and Gtk4LayerShell.is_supported()


# ---------- Monitor geometry helpers ----------

def _get_monitor_rects() -> list[tuple[int, int, int, int]]:
    """Return list of (x, y, w, h) for all monitors."""
    display = Gdk.Display.get_default()
    if not display:
        return []
    monitors = display.get_monitors()
    rects = []
    for i in range(monitors.get_n_items()):
        geo = monitors.get_item(i).get_geometry()
        rects.append((geo.x, geo.y, geo.width, geo.height))
    return rects


def _desktop_bbox(rects: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    """Bounding box of all monitor rects: (min_x, min_y, total_w, total_h)."""
    if not rects:
        return (0, 0, 1920, 1080)
    min_x = min(r[0] for r in rects)
    min_y = min(r[1] for r in rects)
    max_x = max(r[0] + r[2] for r in rects)
    max_y = max(r[1] + r[3] for r in rects)
    return (min_x, min_y, max_x - min_x, max_y - min_y)


# ---------- Drawing primitives ----------

def _draw_glow_rect(cr, x: int, y: int, w: int, h: int,
                    r: float, g: float, b: float, intensity: float) -> None:
    """Draw radial glow centered on a rectangle."""
    import cairo

    cx, cy = x + w / 2, y + h / 2
    max_radius = math.sqrt((w / 2) ** 2 + (h / 2) ** 2)
    inner_radius = max_radius * (1.0 - intensity * 0.6)

    pattern = cairo.RadialGradient(cx, cy, inner_radius, cx, cy, max_radius)
    pattern.add_color_stop_rgba(0, r, g, b, 0.0)
    pattern.add_color_stop_rgba(1, r, g, b, intensity * 0.6)

    cr.save()
    cr.rectangle(x, y, w, h)
    cr.clip()
    cr.set_source(pattern)
    cr.paint()
    cr.restore()


def _draw_border_rect(cr, x: int, y: int, w: int, h: int,
                      r: float, g: float, b: float, intensity: float) -> None:
    """Draw gradient borders inside a rectangle."""
    import cairo

    border_size = int(min(w, h) * 0.08 * intensity)
    if border_size < 1:
        return
    alpha = intensity * 0.7

    cr.save()
    cr.rectangle(x, y, w, h)
    cr.clip()

    for direction, gx, gy, gw, gh in [
        ("down", x, y, w, border_size),
        ("up", x, y + h - border_size, w, border_size),
        ("right", x, y, border_size, h),
        ("left", x + w - border_size, y, border_size, h),
    ]:
        if direction == "down":
            pat = cairo.LinearGradient(gx, gy, gx, gy + gh)
        elif direction == "up":
            pat = cairo.LinearGradient(gx, gy + gh, gx, gy)
        elif direction == "right":
            pat = cairo.LinearGradient(gx, gy, gx + gw, gy)
        else:
            pat = cairo.LinearGradient(gx + gw, gy, gx, gy)

        pat.add_color_stop_rgba(0, r, g, b, alpha)
        pat.add_color_stop_rgba(1, r, g, b, 0.0)

        cr.set_source(pat)
        cr.rectangle(gx, gy, gw, gh)
        cr.fill()

    cr.restore()


def _draw_solid_rect(cr, x: int, y: int, w: int, h: int,
                     r: float, g: float, b: float, intensity: float) -> None:
    cr.set_source_rgba(r, g, b, intensity * 0.4)
    cr.rectangle(x, y, w, h)
    cr.fill()


# ---------- Layer Shell overlay (per-monitor, Sway/Hyprland) ----------

class _LayerShellOverlay(Gtk.Window):
    """One overlay per monitor using wlr-layer-shell."""

    def __init__(self, monitor: Gdk.Monitor) -> None:
        super().__init__()
        self._intensity = 0.0
        self._warning_mode = WarningMode.GLOW

        self.set_decorated(False)
        self.set_can_focus(False)

        da = Gtk.DrawingArea()
        da.set_draw_func(self._on_draw)
        self.set_child(da)
        self._da = da

        # CSS transparency
        css = Gtk.CssProvider()
        css.load_from_string(
            "window.dorso-overlay, window.dorso-overlay > * "
            "{ background: none; background-color: transparent; }"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.add_css_class("dorso-overlay")

        # Input passthrough
        self.connect("realize", self._set_passthrough)

        # Layer shell setup
        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_monitor(self, monitor)
        Gtk4LayerShell.set_exclusive_zone(self, -1)
        for edge in (
            Gtk4LayerShell.Edge.TOP, Gtk4LayerShell.Edge.BOTTOM,
            Gtk4LayerShell.Edge.LEFT, Gtk4LayerShell.Edge.RIGHT,
        ):
            Gtk4LayerShell.set_anchor(self, edge, True)
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.NONE)

        geo = monitor.get_geometry()
        logger.info("Layer Shell overlay on %s (%dx%d)", monitor.get_connector(), geo.width, geo.height)

    def _set_passthrough(self, widget):
        import cairo as _cairo
        surface = self.get_surface()
        if surface:
            surface.set_input_region(_cairo.Region())

    def set_intensity(self, intensity: float) -> None:
        self._intensity = max(0.0, min(1.0, intensity))
        if self._intensity > 0:
            self.set_visible(True)
            self._da.queue_draw()
        else:
            self.set_visible(False)

    def set_warning_mode(self, mode: WarningMode) -> None:
        self._warning_mode = mode
        if self._intensity > 0:
            self._da.queue_draw()

    def _on_draw(self, area, cr, w, h):
        import cairo
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        if self._intensity <= 0:
            return
        r, g, b = WARNING_COLOR
        if self._warning_mode == WarningMode.SOLID:
            _draw_solid_rect(cr, 0, 0, w, h, r, g, b, self._intensity)
        elif self._warning_mode == WarningMode.BORDER:
            _draw_border_rect(cr, 0, 0, w, h, r, g, b, self._intensity)
        else:
            _draw_glow_rect(cr, 0, 0, w, h, r, g, b, self._intensity)


# ---------- Generic overlay (one window, multi-monitor draw) ----------

class _GenericOverlay(Gtk.Window):
    """Single maximized transparent window covering the whole desktop.

    Draws effects per-monitor so each screen gets its own centered glow/border.
    """

    def __init__(self, monitor_rects: list[tuple[int, int, int, int]]) -> None:
        super().__init__()
        self._monitor_rects = monitor_rects
        self._intensity = 0.0
        self._warning_mode = WarningMode.GLOW

        self.set_decorated(False)
        self.set_can_focus(False)

        # Size to full desktop bounding box
        _, _, total_w, total_h = _desktop_bbox(monitor_rects)
        self.set_default_size(total_w, total_h)

        da = Gtk.DrawingArea()
        da.set_draw_func(self._on_draw)
        self.set_child(da)
        self._da = da

        # CSS transparency
        css = Gtk.CssProvider()
        css.load_from_string(
            "window.dorso-overlay, window.dorso-overlay > * "
            "{ background: none; background-color: transparent; }"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.add_css_class("dorso-overlay")

        # Input passthrough
        self.connect("realize", self._set_passthrough)

        connectors = ", ".join(f"{w}x{h}" for _, _, w, h in monitor_rects)
        logger.info("Generic overlay spanning %d monitors (%s), desktop %dx%d",
                     len(monitor_rects), connectors, total_w, total_h)

    def _set_passthrough(self, widget):
        import cairo as _cairo
        surface = self.get_surface()
        if surface:
            surface.set_input_region(_cairo.Region())

    def set_intensity(self, intensity: float) -> None:
        self._intensity = max(0.0, min(1.0, intensity))
        if self._intensity > 0:
            if not self.get_visible():
                self.set_visible(True)
                self.maximize()
            self._da.queue_draw()
        else:
            self.set_visible(False)

    def set_warning_mode(self, mode: WarningMode) -> None:
        self._warning_mode = mode
        if self._intensity > 0:
            self._da.queue_draw()

    def _on_draw(self, area, cr, canvas_w, canvas_h):
        import cairo

        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        if self._intensity <= 0:
            return

        r, g, b = WARNING_COLOR
        bbox = _desktop_bbox(self._monitor_rects)

        for mx, my, mw, mh in self._monitor_rects:
            # Translate monitor coords to window coords
            # Window starts at bbox origin after maximize
            wx = mx - bbox[0]
            wy = my - bbox[1]

            if self._warning_mode == WarningMode.SOLID:
                _draw_solid_rect(cr, wx, wy, mw, mh, r, g, b, self._intensity)
            elif self._warning_mode == WarningMode.BORDER:
                _draw_border_rect(cr, wx, wy, mw, mh, r, g, b, self._intensity)
            else:
                _draw_glow_rect(cr, wx, wy, mw, mh, r, g, b, self._intensity)


# ---------- Public API ----------

class OverlayManager:
    """Manages overlay windows across all monitors."""

    def __init__(self) -> None:
        self._overlays: list[_LayerShellOverlay | _GenericOverlay] = []
        self._warning_mode = WarningMode.GLOW
        self._available = False

    def setup(self) -> None:
        """Create overlay(s) for all monitors."""
        display = Gdk.Display.get_default()
        if display is None:
            logger.error("No display available")
            return

        monitors = display.get_monitors()
        n = monitors.get_n_items()
        logger.info("Setting up overlays for %d monitor(s)", n)

        if _use_layer_shell():
            # One overlay per monitor (Layer Shell handles placement)
            for i in range(n):
                monitor = monitors.get_item(i)
                try:
                    overlay = _LayerShellOverlay(monitor)
                    overlay.set_warning_mode(self._warning_mode)
                    self._overlays.append(overlay)
                except Exception as e:
                    logger.warning("Failed to create Layer Shell overlay for monitor %d: %s", i, e)
        else:
            # Single window spanning all monitors
            rects = _get_monitor_rects()
            if rects:
                overlay = _GenericOverlay(rects)
                overlay.set_warning_mode(self._warning_mode)
                self._overlays.append(overlay)

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
