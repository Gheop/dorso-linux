"""Analytics window — posture stats with charts drawn via Cairo."""

from __future__ import annotations

import math
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, Pango

from dorso.analytics import Analytics

# Colors matching the dorso macOS style
TEAL = (0.24, 0.78, 0.73)
ORANGE = (0.95, 0.65, 0.25)
RED = (0.9, 0.3, 0.25)
GRAY = (0.55, 0.58, 0.62)
DARK = (0.18, 0.20, 0.25)
LIGHT_BG = (0.96, 0.97, 0.98)
WHITE = (1, 1, 1)
CARD_SHADOW = (0, 0, 0, 0.06)


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
        days_fr = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
        return days_fr[dt.weekday()]
    except Exception:
        return iso_date[-2:]


class AnalyticsWindow:
    """Analytics window with Cairo-drawn charts."""

    def __init__(self, analytics: Analytics) -> None:
        self._analytics = analytics

        self._window = Gtk.Window(title="Dorso — Analytiques")
        self._window.set_default_size(520, 520)
        self._window.set_resizable(False)

        # Apply dark header style
        css = Gtk.CssProvider()
        css.load_from_string("""
            .analytics-window {
                background-color: #f5f6f8;
            }
            .analytics-header {
                background-color: #ffffff;
                border-bottom: 1px solid #e0e0e0;
            }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._window.add_css_class("analytics-window")

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

        # Background
        cr.set_source_rgb(*LIGHT_BG)
        cr.paint()

        # ---- Header area ----
        self._draw_rounded_rect(cr, 16, 16, width - 32, 100, 12)
        cr.set_source_rgb(*WHITE)
        cr.fill()

        # Title
        cr.set_source_rgb(*DARK)
        cr.select_font_face("Sans", 0, 1)  # bold
        cr.set_font_size(20)
        cr.move_to(30, 48)
        cr.show_text("Analytiques Posture")

        cr.set_source_rgb(*GRAY)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(12)
        cr.move_to(30, 68)
        cr.show_text("Suivez vos habitudes et votre progression")

        # Today's score (circular gauge) — top right
        score = today.score
        cx, cy, radius = width - 70, 66, 32
        self._draw_score_ring(cr, cx, cy, radius, score)

        # "Score du jour" label
        cr.set_source_rgb(*GRAY)
        cr.set_font_size(9)
        tw = cr.text_extents("Score du jour").width
        cr.move_to(cx - tw / 2, cy - radius - 8)
        cr.show_text("Score du jour")

        # ---- Stats cards ----
        card_y = 132
        card_h = 72
        card_w = (width - 48 - 12) / 3  # 3 cards

        stats = [
            ("Monitoring", _fmt_duration(today.monitoring_seconds), TEAL),
            ("Slouch", _fmt_duration(today.slouch_seconds), ORANGE),
            ("Alertes", str(today.slouch_events), RED),
        ]

        for i, (label, value, color) in enumerate(stats):
            x = 16 + i * (card_w + 6)
            self._draw_rounded_rect(cr, x, card_y, card_w, card_h, 10)
            cr.set_source_rgb(*WHITE)
            cr.fill()

            # Color accent bar
            self._draw_rounded_rect(cr, x, card_y, 4, card_h, 2)
            cr.set_source_rgb(*color)
            cr.fill()

            # Label
            cr.set_source_rgb(*GRAY)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(11)
            cr.move_to(x + 14, card_y + 24)
            cr.show_text(label)

            # Value
            cr.set_source_rgb(*DARK)
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
        cr.set_source_rgb(*WHITE)
        cr.fill()

        # Chart title
        cr.set_source_rgb(*DARK)
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(14)
        cr.move_to(chart_x + 16, chart_y + 28)
        cr.show_text("7 derniers jours")

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
            cr.set_source_rgb(*DARK)
            cr.select_font_face("Sans", 0, 1)
            cr.set_font_size(11)
            score_text = str(day.score)
            tw = cr.text_extents(score_text).width
            cr.move_to(bx + bar_w / 2 - tw / 2, by - 6)
            cr.show_text(score_text)

            # Day label below
            cr.set_source_rgb(*GRAY)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(10)
            label = _day_label(day.date)
            tw = cr.text_extents(label).width
            cr.move_to(bx + bar_w / 2 - tw / 2, bar_area_y + bar_area_h + 16)
            cr.show_text(label)

    def _draw_score_ring(self, cr, cx: float, cy: float, r: float, score: int) -> None:
        """Draw a circular score gauge."""
        import cairo

        # Background ring
        cr.new_sub_path()
        cr.set_line_width(5)
        cr.set_line_cap(cairo.LINE_CAP_BUTT)
        cr.set_source_rgba(*GRAY, 0.2)
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
        cr.set_source_rgb(*DARK)
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
