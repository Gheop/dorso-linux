"""Screen overlay for visual posture warnings.

Strategy:
- Layer Shell (Sway, Hyprland): one transparent overlay per monitor (perfect)
- GNOME Wayland: one maximized transparent window (covers primary monitor)
- X11: one transparent window per monitor with input passthrough
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


# ---------- Drawing primitives ----------

def _draw_glow(cr, w: int, h: int, r: float, g: float, b: float, intensity: float) -> None:
    import cairo

    cx, cy = w / 2, h / 2
    max_r = math.sqrt(cx ** 2 + cy ** 2)
    inner_r = max_r * (1.0 - intensity * 0.6)

    pat = cairo.RadialGradient(cx, cy, inner_r, cx, cy, max_r)
    pat.add_color_stop_rgba(0, r, g, b, 0.0)
    pat.add_color_stop_rgba(1, r, g, b, intensity * 0.6)

    cr.set_source(pat)
    cr.rectangle(0, 0, w, h)
    cr.fill()


def _draw_border(cr, w: int, h: int, r: float, g: float, b: float, intensity: float) -> None:
    import cairo

    border = int(min(w, h) * 0.08 * intensity)
    if border < 1:
        return
    alpha = intensity * 0.7

    for direction, gx, gy, gw, gh in [
        ("down", 0, 0, w, border),
        ("up", 0, h - border, w, border),
        ("right", 0, 0, border, h),
        ("left", w - border, 0, border, h),
    ]:
        if direction == "down":
            p = cairo.LinearGradient(gx, gy, gx, gy + gh)
        elif direction == "up":
            p = cairo.LinearGradient(gx, gy + gh, gx, gy)
        elif direction == "right":
            p = cairo.LinearGradient(gx, gy, gx + gw, gy)
        else:
            p = cairo.LinearGradient(gx + gw, gy, gx, gy)
        p.add_color_stop_rgba(0, r, g, b, alpha)
        p.add_color_stop_rgba(1, r, g, b, 0.0)
        cr.set_source(p)
        cr.rectangle(gx, gy, gw, gh)
        cr.fill()


def _draw_solid(cr, w: int, h: int, r: float, g: float, b: float, intensity: float) -> None:
    cr.set_source_rgba(r, g, b, intensity * 0.4)
    cr.rectangle(0, 0, w, h)
    cr.fill()


def _draw_effect(cr, w, h, mode, intensity):
    r, g, b = WARNING_COLOR
    if mode == WarningMode.BORDER:
        _draw_border(cr, w, h, r, g, b, intensity)
    elif mode == WarningMode.SOLID:
        _draw_solid(cr, w, h, r, g, b, intensity)
    else:
        _draw_glow(cr, w, h, r, g, b, intensity)


# ---------- Transparent overlay window (works on GNOME Wayland + X11) ----------

class _TransparentOverlay(Gtk.Window):
    """Overlay that goes fullscreen only while slouching.

    When idle (intensity=0): window is hidden, no impact on desktop.
    When slouching (intensity>0): window goes fullscreen with
    compositor opacity for transparency. Fullscreen ensures the overlay
    stays above ALL windows. The top bar hides during slouch — that's
    intentional (same UX as dorso macOS which blurs the entire screen).
    Empty input region ensures keyboard/mouse still work.
    """

    def __init__(self, monitor: Gdk.Monitor) -> None:
        super().__init__()
        self._intensity = 0.0
        self._warning_mode = WarningMode.GLOW
        self._is_fullscreen = False

        self.set_decorated(False)
        self.set_can_focus(False)
        self.set_focusable(False)

        da = Gtk.DrawingArea()
        da.set_draw_func(self._on_draw)
        self.set_child(da)
        self._da = da

        self.connect("realize", self._apply_passthrough)

        geo = monitor.get_geometry()
        logger.info("Overlay: %s (%dx%d)", monitor.get_connector(), geo.width, geo.height)

    def _apply_passthrough(self, *args) -> bool:
        import cairo as _c
        s = self.get_surface()
        if s:
            s.set_input_region(_c.Region())
        return False

    def present_once(self) -> None:
        """No-op at startup — window starts hidden."""
        pass

    def set_intensity(self, v: float) -> None:
        old = self._intensity
        self._intensity = max(0.0, min(1.0, v))

        if v > 0 and not self._is_fullscreen:
            # Go fullscreen to stay above everything
            self.set_opacity(0.0)
            self.set_visible(True)
            self.fullscreen()
            self._is_fullscreen = True
            # Apply passthrough after compositor processes fullscreen
            for delay in (50, 200, 500):
                GLib.timeout_add(delay, self._apply_passthrough)

        if v > 0:
            # Update opacity — compositor handles transparency
            self.set_opacity(v * 0.45)
            self._da.queue_draw()
        elif old > 0 and v == 0:
            # Slouching ended — unfullscreen and hide
            self.unfullscreen()
            self.set_visible(False)
            self._is_fullscreen = False

    def set_warning_mode(self, m: WarningMode) -> None:
        self._warning_mode = m
        if self._intensity > 0:
            self._da.queue_draw()

    def _on_draw(self, area, cr, w, h):
        # Black background (compositor opacity makes it transparent)
        cr.set_source_rgba(0, 0, 0, 1)
        cr.paint()

        if self._intensity > 0:
            r, g, b = WARNING_COLOR
            if self._warning_mode == WarningMode.BORDER:
                _draw_border(cr, w, h, r, g, b, 1.0)
            elif self._warning_mode == WarningMode.SOLID:
                _draw_solid(cr, w, h, r, g, b, 1.0)
            else:
                _draw_glow(cr, w, h, r, g, b, 1.0)


# ---------- Layer Shell overlay (Sway/Hyprland) ----------

class _LayerShellOverlay(Gtk.Window):
    """Per-monitor overlay via wlr-layer-shell."""

    def __init__(self, monitor: Gdk.Monitor) -> None:
        super().__init__()
        self._intensity = 0.0
        self._warning_mode = WarningMode.GLOW

        self.set_decorated(False)
        self.set_can_focus(False)

        css = Gtk.CssProvider()
        css.load_from_string(
            "window.dorso-overlay, window.dorso-overlay > * "
            "{ background: none; background-color: transparent; }"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.add_css_class("dorso-overlay")

        da = Gtk.DrawingArea()
        da.set_draw_func(self._on_draw)
        self.set_child(da)
        self._da = da

        self.connect("realize", self._on_realize)

        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_monitor(self, monitor)
        Gtk4LayerShell.set_exclusive_zone(self, -1)
        for edge in (Gtk4LayerShell.Edge.TOP, Gtk4LayerShell.Edge.BOTTOM,
                     Gtk4LayerShell.Edge.LEFT, Gtk4LayerShell.Edge.RIGHT):
            Gtk4LayerShell.set_anchor(self, edge, True)
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.NONE)

        geo = monitor.get_geometry()
        logger.info("Layer Shell overlay: %s (%dx%d)", monitor.get_connector(), geo.width, geo.height)

    def _on_realize(self, w):
        import cairo as _c
        s = self.get_surface()
        if s:
            s.set_input_region(_c.Region())

    def set_intensity(self, v: float) -> None:
        self._intensity = max(0.0, min(1.0, v))
        if self._intensity > 0:
            self.set_visible(True)
            self._da.queue_draw()
        else:
            self.set_visible(False)

    def set_warning_mode(self, m: WarningMode) -> None:
        self._warning_mode = m
        if self._intensity > 0:
            self._da.queue_draw()

    def _on_draw(self, area, cr, w, h):
        import cairo
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        if self._intensity > 0:
            _draw_effect(cr, w, h, self._warning_mode, self._intensity)


# ---------- Public API ----------

class OverlayManager:
    """Manages overlay windows."""

    def __init__(self) -> None:
        self._overlays: list = []
        self._warning_mode = WarningMode.GLOW
        self._available = False

    def setup(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            logger.error("No display available")
            return

        monitors = display.get_monitors()
        n = monitors.get_n_items()
        logger.info("Setting up overlays for %d monitor(s)", n)

        if _use_layer_shell():
            # Layer Shell: one overlay per monitor (perfect multi-monitor)
            for i in range(n):
                try:
                    o = _LayerShellOverlay(monitors.get_item(i))
                    o.set_warning_mode(self._warning_mode)
                    self._overlays.append(o)
                except Exception as e:
                    logger.warning("Layer Shell overlay failed for monitor %d: %s", i, e)
        else:
            # GNOME Wayland / X11: always-visible transparent window
            o = _TransparentOverlay(monitors.get_item(0))
            o.set_warning_mode(self._warning_mode)
            self._overlays.append(o)
            # Show and maximize once — stays up forever (draws nothing when idle)
            o.present_once()

        self._available = len(self._overlays) > 0

    @property
    def available(self) -> bool:
        return self._available

    def set_intensity(self, intensity: float) -> None:
        for o in self._overlays:
            o.set_intensity(intensity)

    def set_warning_mode(self, mode: WarningMode) -> None:
        self._warning_mode = mode
        for o in self._overlays:
            o.set_warning_mode(mode)

    def clear(self) -> None:
        self.set_intensity(0.0)

    def destroy(self) -> None:
        for o in self._overlays:
            o.destroy()
        self._overlays.clear()
