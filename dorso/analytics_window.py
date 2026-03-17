"""Analytics window — posture stats with charts drawn via Cairo."""

from __future__ import annotations

import math
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, Pango

from dorso.analytics import Analytics
from dorso.i18n import _

# Accent colors (always the same regardless of theme)
TEAL = (0.24, 0.78, 0.73)
ORANGE = (0.95, 0.65, 0.25)
RED = (0.9, 0.3, 0.25)


def _get_theme_colors() -> dict:
    """Read colors from the current GTK theme (supports dark/light)."""
    display = Gdk.Display.get_default()
    if not display:
        # Fallback light theme
        return {"bg": (0.96, 0.97, 0.98), "card": (1, 1, 1),
                "fg": (0.18, 0.20, 0.25), "dim": (0.55, 0.58, 0.62)}

    # Detect dark mode via the style manager or color scheme
    settings = Gtk.Settings.get_for_display(display)
    prefer_dark = settings.get_property("gtk-application-prefer-dark-theme")

    # Also check GNOME color-scheme
    if not prefer_dark:
        try:
            import subprocess
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True, timeout=1,
            )
            prefer_dark = "dark" in result.stdout.lower()
        except Exception:
            pass

    if prefer_dark:
        return {
            "bg": (0.15, 0.15, 0.17),
            "card": (0.22, 0.22, 0.25),
            "fg": (0.92, 0.92, 0.94),
            "dim": (0.55, 0.55, 0.58),
        }
    else:
        return {
            "bg": (0.96, 0.97, 0.98),
            "card": (1, 1, 1),
            "fg": (0.18, 0.20, 0.25),
            "dim": (0.55, 0.58, 0.62),
        }


def _fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    elif m > 0:
        return f"{m}m {s:02d}s"
    else:
        return f"{s}s"


def _day_label(iso_date: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_date)
        days = [_("Mon"), _("Tue"), _("Wed"), _("Thu"), _("Fri"), _("Sat"), _("Sun")]
        return days[dt.weekday()]
    except Exception:
        return iso_date[-2:]


class AnalyticsWindow:
    """Analytics window with Cairo-drawn charts."""

    def __init__(self, analytics: Analytics) -> None:
        self._analytics = analytics

        self._window = Gtk.Window(title=_("Dorso — Analytics"))
        self._window.set_default_size(520, 520)
        self._window.set_resizable(False)

        # No custom CSS — colors are read from theme in _on_draw

        da = Gtk.DrawingArea()
        da.set_draw_func(self._on_draw)
        da.set_content_width(520)
        da.set_content_height(520)
        self._window.set_child(da)

    def show(self) -> None:
        self._window.set_visible(True)

    def _on_draw(self, area, cr, width, height) -> None:
        today = self._analytics.today
        week = self._analytics.last_n_days(7)
        tc = _get_theme_colors()

        # Background
        cr.set_source_rgb(*tc["bg"])
        cr.paint()

        # ---- Header area ----
        self._draw_rounded_rect(cr, 16, 16, width - 32, 100, 12)
        cr.set_source_rgb(*tc["card"])
        cr.fill()

        # Title
        cr.set_source_rgb(*tc["fg"])
        cr.select_font_face("Sans", 0, 1)  # bold
        cr.set_font_size(20)
        cr.move_to(30, 48)
        cr.show_text(_("Posture Analytics"))

        cr.set_source_rgb(*tc["dim"])
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(12)
        cr.move_to(30, 68)
        cr.show_text(_("Track your habits and progress"))

        # Today's score (circular gauge) — top right
        score = today.score
        cx, cy, radius = width - 70, 66, 32
        self._draw_score_ring(cr, cx, cy, radius, score, tc)

        # "Score du jour" label
        cr.set_source_rgb(*tc["dim"])
        cr.set_font_size(9)
        _today_score = _("Today's score")
        tw = cr.text_extents(_today_score).width
        cr.move_to(cx - tw / 2, cy - radius - 8)
        cr.show_text(_today_score)

        # ---- Stats cards ----
        card_y = 132
        card_h = 72
        card_w = (width - 48 - 12) / 3  # 3 cards

        stats = [
            (_("Monitoring"), _fmt_duration(today.monitoring_seconds), TEAL),
            (_("Slouch"), _fmt_duration(today.slouch_seconds), ORANGE),
            (_("Alerts"), str(today.slouch_events), RED),
        ]

        for i, (label, value, color) in enumerate(stats):
            x = 16 + i * (card_w + 6)
            self._draw_rounded_rect(cr, x, card_y, card_w, card_h, 10)
            cr.set_source_rgb(*tc["card"])
            cr.fill()

            # Color accent bar
            self._draw_rounded_rect(cr, x, card_y, 4, card_h, 2)
            cr.set_source_rgb(*color)
            cr.fill()

            # Label
            cr.set_source_rgb(*tc["dim"])
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(11)
            cr.move_to(x + 14, card_y + 24)
            cr.show_text(label)

            # Value
            cr.set_source_rgb(*tc["fg"])
            cr.select_font_face("Sans", 0, 1)
            cr.set_font_size(20)
            cr.move_to(x + 14, card_y + 52)
            cr.show_text(value)

        # ---- 7-day bar chart ----
        chart_y = card_y + card_h + 20
        chart_h = height - chart_y - 30
        chart_x = 16
        chart_w = width - 32

        # Chart card background
        self._draw_rounded_rect(cr, chart_x, chart_y, chart_w, chart_h, 12)
        cr.set_source_rgb(*tc["card"])
        cr.fill()

        # Chart title
        cr.set_source_rgb(*tc["fg"])
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(14)
        cr.move_to(chart_x + 16, chart_y + 28)
        cr.show_text(_("Last 7 days"))

        # Bar chart area
        bar_area_x = chart_x + 16
        bar_area_y = chart_y + 44
        bar_area_w = chart_w - 32
        bar_area_h = chart_h - 74

        if not week:
            return

        n = len(week)
        bar_gap = 8
        bar_w = (bar_area_w - (n - 1) * bar_gap) / n
        max_score = 100

        for i, day in enumerate(week):
            bx = bar_area_x + i * (bar_w + bar_gap)
            bar_h = (day.score / max_score) * bar_area_h if max_score > 0 else 0
            by = bar_area_y + bar_area_h - bar_h

            # Bar color: gradient from orange (low) to teal (high)
            t = day.score / 100
            r = ORANGE[0] * (1 - t) + TEAL[0] * t
            g = ORANGE[1] * (1 - t) + TEAL[1] * t
            b = ORANGE[2] * (1 - t) + TEAL[2] * t

            # Bar with rounded top
            self._draw_rounded_rect(cr, bx, by, bar_w, bar_h, 4)
            cr.set_source_rgb(r, g, b)
            cr.fill()

            # Score label above bar
            cr.set_source_rgb(*tc["fg"])
            cr.select_font_face("Sans", 0, 1)
            cr.set_font_size(11)
            score_text = str(day.score)
            tw = cr.text_extents(score_text).width
            cr.move_to(bx + bar_w / 2 - tw / 2, by - 6)
            cr.show_text(score_text)

            # Day label below
            cr.set_source_rgb(*tc["dim"])
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(10)
            label = _day_label(day.date)
            tw = cr.text_extents(label).width
            cr.move_to(bx + bar_w / 2 - tw / 2, bar_area_y + bar_area_h + 16)
            cr.show_text(label)

    def _draw_score_ring(self, cr, cx: float, cy: float, r: float, score: int, tc: dict) -> None:
        """Draw a circular score gauge."""
        import cairo

        # Background ring
        cr.new_sub_path()
        cr.set_line_width(5)
        cr.set_line_cap(cairo.LINE_CAP_BUTT)
        cr.set_source_rgba(*tc["dim"], 0.2)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()

        # Score arc
        if score > 0:
            if score >= 70:
                color = TEAL
            elif score >= 40:
                color = ORANGE
            else:
                color = RED

            cr.new_sub_path()
            cr.set_line_width(5)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.set_source_rgb(*color)
            start = -math.pi / 2
            end = start + (score / 100) * 2 * math.pi
            cr.arc(cx, cy, r, start, end)
            cr.stroke()

        # Score text
        cr.set_source_rgb(*tc["fg"])
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(18)
        text = f"{score}%"
        ext = cr.text_extents(text)
        cr.move_to(cx - ext.width / 2, cy + ext.height / 2)
        cr.show_text(text)

    @staticmethod
    def _draw_rounded_rect(cr, x, y, w, h, r) -> None:
        """Draw a rounded rectangle path."""
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
