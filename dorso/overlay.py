"""Screen overlay for visual posture warnings.

Multi-monitor strategy:
- Layer Shell (Sway, Hyprland): one transparent overlay per monitor
- GNOME Wayland: one fullscreen window spanning all monitors,
  compositor-level opacity for transparency, per-monitor drawing
- X11: one transparent window per monitor with input passthrough
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


# ---------- Monitor geometry ----------

def _get_monitor_rects() -> list[tuple[int, int, int, int]]:
    """Return (x, y, w, h) for each monitor."""
    display = Gdk.Display.get_default()
    if not display:
        return []
    monitors = display.get_monitors()
    return [
        (g.x, g.y, g.width, g.height)
        for i in range(monitors.get_n_items())
        for g in [monitors.get_item(i).get_geometry()]
    ]


# ---------- Per-monitor drawing primitives ----------

def _draw_glow(cr, x: int, y: int, w: int, h: int,
               r: float, g: float, b: float, alpha: float) -> None:
    import cairo

    cx, cy = x + w / 2, y + h / 2
    max_r = math.sqrt((w / 2) ** 2 + (h / 2) ** 2)
    inner_r = max_r * 0.4

    pat = cairo.RadialGradient(cx, cy, inner_r, cx, cy, max_r)
    pat.add_color_stop_rgba(0, r, g, b, 0.0)
    pat.add_color_stop_rgba(1, r, g, b, alpha)

    cr.save()
    cr.rectangle(x, y, w, h)
    cr.clip()
    cr.set_source(pat)
    cr.paint()
    cr.restore()


def _draw_border(cr, x: int, y: int, w: int, h: int,
                 r: float, g: float, b: float, alpha: float) -> None:
    import cairo

    border = int(min(w, h) * 0.08)
    if border < 1:
        return

    cr.save()
    cr.rectangle(x, y, w, h)
    cr.clip()

    for direction, gx, gy, gw, gh in [
        ("down", x, y, w, border),
        ("up", x, y + h - border, w, border),
        ("right", x, y, border, h),
        ("left", x + w - border, y, border, h),
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

    cr.restore()


def _draw_solid(cr, x: int, y: int, w: int, h: int,
                r: float, g: float, b: float, alpha: float) -> None:
    cr.set_source_rgba(r, g, b, alpha)
    cr.rectangle(x, y, w, h)
    cr.fill()


def _draw_effect(cr, rects, mode, r, g, b, alpha):
    """Draw the chosen effect on each monitor rect."""
    for mx, my, mw, mh in rects:
        if mode == WarningMode.BORDER:
            _draw_border(cr, mx, my, mw, mh, r, g, b, alpha)
        elif mode == WarningMode.SOLID:
            _draw_solid(cr, mx, my, mw, mh, r, g, b, alpha)
        else:
            _draw_glow(cr, mx, my, mw, mh, r, g, b, alpha)


# ---------- Layer Shell overlay (Sway/Hyprland) ----------

class _LayerShellOverlay(Gtk.Window):
    """Per-monitor overlay via wlr-layer-shell. Transparent via cairo alpha."""

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

        # Transparent CSS
        css = Gtk.CssProvider()
        css.load_from_string(
            "window.dorso-overlay, window.dorso-overlay > * "
            "{ background: none; background-color: transparent; }"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.add_css_class("dorso-overlay")
        self.connect("realize", self._on_realize)

        # Layer shell
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
            r, g, b = WARNING_COLOR
            _draw_effect(cr, [(0, 0, w, h)], self._warning_mode,
                         r, g, b, self._intensity * 0.6)


# ---------- GNOME Wayland overlay (fullscreen + compositor opacity) ----------

class _GnomeOverlay(Gtk.Window):
    """Fullscreen window with compositor-controlled opacity.

    fullscreen() on GNOME spans all monitors but forces an opaque
    background. We use set_opacity() so Mutter blends the whole
    window, and draw effects opaquely per-monitor region.
    """

    def __init__(self, monitor_rects: list[tuple[int, int, int, int]]) -> None:
        super().__init__()
        self._rects = monitor_rects
        self._intensity = 0.0
        self._warning_mode = WarningMode.GLOW

        self.set_decorated(False)
        self.set_can_focus(False)

        da = Gtk.DrawingArea()
        da.set_draw_func(self._on_draw)
        self.set_child(da)
        self._da = da

        self.connect("realize", self._on_realize)

        names = ", ".join(f"{w}x{h}" for _, _, w, h in monitor_rects)
        logger.info("GNOME overlay: fullscreen + compositor opacity (%s)", names)

    def _on_realize(self, w):
        import cairo as _c
        s = self.get_surface()
        if s:
            s.set_input_region(_c.Region())

    def set_intensity(self, v: float) -> None:
        self._intensity = max(0.0, min(1.0, v))
        if self._intensity > 0:
            if not self.get_visible():
                self.set_visible(True)
                self.fullscreen()
            # Compositor opacity: maps intensity to 0..0.5 max
            self.set_opacity(self._intensity * 0.5)
            self._da.queue_draw()
        else:
            self.set_opacity(0.0)
            self.set_visible(False)

    def set_warning_mode(self, m: WarningMode) -> None:
        self._warning_mode = m
        if self._intensity > 0:
            self._da.queue_draw()

    def _on_draw(self, area, cr, cw, ch):
        # Black background (compositor opacity makes it transparent)
        cr.set_source_rgba(0, 0, 0, 1)
        cr.paint()

        if self._intensity <= 0:
            return

        r, g, b = WARNING_COLOR
        # Draw effects per-monitor, fully opaque (compositor handles alpha)
        _draw_effect(cr, self._rects, self._warning_mode, r, g, b, 1.0)


# ---------- X11 overlay (per-monitor, CSS transparency) ----------

class _X11Overlay(Gtk.Window):
    """Per-monitor transparent window on X11."""

    def __init__(self, monitor: Gdk.Monitor) -> None:
        super().__init__()
        self._intensity = 0.0
        self._warning_mode = WarningMode.GLOW

        geo = monitor.get_geometry()
        self._rect = (0, 0, geo.width, geo.height)

        self.set_decorated(False)
        self.set_can_focus(False)
        self.set_default_size(geo.width, geo.height)

        da = Gtk.DrawingArea()
        da.set_draw_func(self._on_draw)
        self.set_child(da)
        self._da = da

        css = Gtk.CssProvider()
        css.load_from_string(
            "window.dorso-overlay, window.dorso-overlay > * "
            "{ background: none; background-color: transparent; }"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.add_css_class("dorso-overlay")
        self.connect("realize", self._on_realize)

        logger.info("X11 overlay: %s (%dx%d)", monitor.get_connector(), geo.width, geo.height)

    def _on_realize(self, w):
        import cairo as _c
        s = self.get_surface()
        if s:
            s.set_input_region(_c.Region())

    def set_intensity(self, v: float) -> None:
        self._intensity = max(0.0, min(1.0, v))
        if self._intensity > 0:
            if not self.get_visible():
                self.set_visible(True)
                self.fullscreen()
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
            r, g, b = WARNING_COLOR
            _draw_effect(cr, [self._rect], self._warning_mode,
                         r, g, b, self._intensity * 0.6)


# ---------- Public API ----------

class OverlayManager:
    """Manages overlay windows across all monitors."""

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
            for i in range(n):
                try:
                    o = _LayerShellOverlay(monitors.get_item(i))
                    o.set_warning_mode(self._warning_mode)
                    self._overlays.append(o)
                except Exception as e:
                    logger.warning("Layer Shell overlay failed for monitor %d: %s", i, e)
        elif _is_wayland():
            rects = _get_monitor_rects()
            if rects:
                o = _GnomeOverlay(rects)
                o.set_warning_mode(self._warning_mode)
                self._overlays.append(o)
        else:
            for i in range(n):
                try:
                    o = _X11Overlay(monitors.get_item(i))
                    o.set_warning_mode(self._warning_mode)
                    self._overlays.append(o)
                except Exception as e:
                    logger.warning("X11 overlay failed for monitor %d: %s", i, e)

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
