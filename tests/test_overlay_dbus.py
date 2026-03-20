"""Tests for the D-Bus overlay proxy (_GnomeShellOverlay).

All D-Bus calls are mocked — no session bus or GNOME Shell needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dorso.models import WarningMode


class TestGnomeShellOverlayAvailability:
    """Test availability check and fallback logic."""

    @patch("dorso.overlay.Gio")
    def test_extension_available(self, mock_gio):
        """When D-Bus reports the name is owned → available() returns True."""
        from dorso.overlay import _GnomeShellOverlay

        mock_bus = MagicMock()
        mock_gio.bus_get_sync.return_value = mock_bus

        # NameHasOwner returns (True,)
        mock_result = MagicMock()
        mock_result.unpack.return_value = (True,)
        mock_bus.call_sync.return_value = mock_result

        assert _GnomeShellOverlay.available() is True

    @patch("dorso.overlay.Gio")
    def test_extension_unavailable(self, mock_gio):
        """When D-Bus reports name not owned → available() returns False."""
        from dorso.overlay import _GnomeShellOverlay

        mock_bus = MagicMock()
        mock_gio.bus_get_sync.return_value = mock_bus

        mock_result = MagicMock()
        mock_result.unpack.return_value = (False,)
        mock_bus.call_sync.return_value = mock_result

        assert _GnomeShellOverlay.available() is False

    @patch("dorso.overlay.Gio")
    def test_extension_dbus_error_returns_false(self, mock_gio):
        """D-Bus errors should be caught → available() returns False."""
        from dorso.overlay import _GnomeShellOverlay

        mock_gio.bus_get_sync.side_effect = Exception("no bus")
        assert _GnomeShellOverlay.available() is False


class TestGnomeShellOverlaySetIntensity:
    """set_intensity() should call SetOverlay via the D-Bus proxy."""

    @patch("dorso.overlay.GLib")
    @patch("dorso.overlay.Gio")
    def test_set_intensity_calls_set_overlay(self, mock_gio, mock_glib):
        """Positive intensity → proxy.call_sync('SetOverlay', ...)."""
        from dorso.overlay import _GnomeShellOverlay

        overlay = _GnomeShellOverlay()
        overlay._proxy = MagicMock()

        overlay.set_intensity(0.7)

        overlay._proxy.call_sync.assert_called_once()
        call_args = overlay._proxy.call_sync.call_args
        assert call_args[0][0] == "SetOverlay"

    @patch("dorso.overlay.GLib")
    @patch("dorso.overlay.Gio")
    def test_zero_intensity_calls_clear(self, mock_gio, mock_glib):
        """Zero intensity → proxy.call_sync('Clear', ...)."""
        from dorso.overlay import _GnomeShellOverlay

        overlay = _GnomeShellOverlay()
        overlay._proxy = MagicMock()

        overlay.set_intensity(0.0)

        overlay._proxy.call_sync.assert_called_once()
        call_args = overlay._proxy.call_sync.call_args
        assert call_args[0][0] == "Clear"


class TestGnomeShellOverlayClear:
    """clear (set_intensity(0)) should call Clear on the proxy."""

    @patch("dorso.overlay.GLib")
    @patch("dorso.overlay.Gio")
    def test_clear_via_intensity(self, mock_gio, mock_glib):
        from dorso.overlay import _GnomeShellOverlay

        overlay = _GnomeShellOverlay()
        overlay._proxy = MagicMock()
        overlay._intensity = 0.5  # was active

        overlay.set_intensity(0.0)

        overlay._proxy.call_sync.assert_called_once()
        assert overlay._proxy.call_sync.call_args[0][0] == "Clear"


class TestGnomeShellOverlayDestroy:
    """destroy() should send Clear and reset proxy."""

    @patch("dorso.overlay.GLib")
    @patch("dorso.overlay.Gio")
    def test_destroy_clears_and_resets(self, mock_gio, mock_glib):
        from dorso.overlay import _GnomeShellOverlay

        overlay = _GnomeShellOverlay()
        mock_proxy = MagicMock()
        overlay._proxy = mock_proxy

        overlay.destroy()

        mock_proxy.call_sync.assert_called_once()
        assert mock_proxy.call_sync.call_args[0][0] == "Clear"
        # After destroy, proxy should be None
        assert overlay._proxy is None


class TestGnomeShellOverlayNoProxy:
    """Operations with no proxy should not raise."""

    def test_set_intensity_no_proxy(self):
        from dorso.overlay import _GnomeShellOverlay

        overlay = _GnomeShellOverlay()
        # Should not raise
        overlay.set_intensity(0.5)

    def test_set_warning_mode(self):
        from dorso.overlay import _GnomeShellOverlay

        overlay = _GnomeShellOverlay()
        overlay.set_warning_mode(WarningMode.BORDER)
        assert overlay._warning_mode == WarningMode.BORDER

    def test_set_color(self):
        from dorso.overlay import _GnomeShellOverlay

        overlay = _GnomeShellOverlay()
        overlay.set_color((0.1, 0.2, 0.3))
        assert overlay._color == (0.1, 0.2, 0.3)


class TestDrawingPrimitives:
    """Test the pure drawing functions with a mock Cairo context."""

    def test_draw_glow(self):
        from dorso.overlay import _draw_glow
        cr = MagicMock()
        _draw_glow(cr, 1920, 1080, 0.9, 0.2, 0.1, 0.5)
        cr.set_source.assert_called_once()
        cr.rectangle.assert_called_once_with(0, 0, 1920, 1080)
        cr.fill.assert_called_once()

    def test_draw_border(self):
        from dorso.overlay import _draw_border
        cr = MagicMock()
        _draw_border(cr, 1920, 1080, 0.9, 0.2, 0.1, 0.5)
        # 4 sides = 4 fills
        assert cr.fill.call_count == 4
        assert cr.rectangle.call_count == 4

    def test_draw_border_zero_intensity_skips(self):
        from dorso.overlay import _draw_border
        cr = MagicMock()
        _draw_border(cr, 1920, 1080, 0.9, 0.2, 0.1, 0.0)
        # border < 1 → return early
        cr.fill.assert_not_called()

    def test_draw_solid(self):
        from dorso.overlay import _draw_solid
        cr = MagicMock()
        _draw_solid(cr, 1920, 1080, 0.9, 0.2, 0.1, 0.5)
        cr.set_source_rgba.assert_called_once_with(0.9, 0.2, 0.1, 0.2)
        cr.rectangle.assert_called_once_with(0, 0, 1920, 1080)
        cr.fill.assert_called_once()

    @patch("dorso.overlay.cairo")
    def test_draw_overlay_dispatches_glow(self, mock_cairo):
        from dorso.overlay import _draw_overlay
        cr = MagicMock()
        _draw_overlay(cr, 800, 600, WarningMode.GLOW, (0.9, 0.2, 0.1), 0.5)
        # Should have called set_source (from _draw_glow)
        cr.set_source.assert_called()

    @patch("dorso.overlay.cairo")
    def test_draw_overlay_zero_intensity_clears_only(self, mock_cairo):
        from dorso.overlay import _draw_overlay
        cr = MagicMock()
        _draw_overlay(cr, 800, 600, WarningMode.GLOW, (0.9, 0.2, 0.1), 0.0)
        cr.paint.assert_called_once()
        # No drawing calls after paint
        cr.set_source.assert_not_called()
        cr.fill.assert_not_called()


class TestIsWayland:
    def test_wayland_detected(self, monkeypatch):
        from dorso.overlay import _is_wayland
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        assert _is_wayland() is True

    def test_no_wayland(self, monkeypatch):
        from dorso.overlay import _is_wayland
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert _is_wayland() is False


class TestOverlayManagerFallback:
    """OverlayManager falls back when extension is unavailable."""

    @patch("dorso.overlay._GnomeShellOverlay.available", return_value=False)
    @patch("dorso.overlay.Gdk")
    def test_fallback_when_no_extension(self, mock_gdk, mock_avail):
        """Without extension + no display → empty overlays list."""
        from dorso.overlay import OverlayManager

        mock_gdk.Display.get_default.return_value = None

        mgr = OverlayManager()
        mgr.setup()

        assert not mgr.available
        assert len(mgr._overlays) == 0
