"""Unit tests for TrayIcon D-Bus signal emission."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from dorso.tray import SNI_INTERFACE, SNI_PATH, TrayIcon


@pytest.fixture
def tray():
    """Create a TrayIcon with a mock D-Bus connection."""
    icon = TrayIcon(
        on_toggle=MagicMock(),
        on_calibrate=MagicMock(),
        on_settings=MagicMock(),
        on_analytics=MagicMock(),
        on_quit=MagicMock(),
    )
    icon._bus = MagicMock()
    icon._sni_reg_id = 1
    return icon


class TestUpdateState:
    def test_emits_new_icon_and_properties_changed(self, tray):
        tray.update_state("good")

        calls = tray._bus.emit_signal.call_args_list
        # First call: NewIcon
        assert calls[0] == call(None, SNI_PATH, SNI_INTERFACE, "NewIcon", None)
        # Second call: PropertiesChanged (dest, path, iface, signal, variant)
        args = calls[1][0]
        assert args[1] == SNI_PATH
        assert args[2] == "org.freedesktop.DBus.Properties"
        assert args[3] == "PropertiesChanged"

    def test_state_mapping(self, tray):
        """Each valid state should update _current_state."""
        for state in ("good", "bad", "away", "paused", "calibrating", "disabled"):
            tray.update_state(state)
            assert tray._current_state == state

    def test_invalid_state_ignored(self, tray):
        tray.update_state("disabled")
        tray._bus.emit_signal.reset_mock()

        tray.update_state("invalid_state")
        assert tray._current_state == "disabled"
        tray._bus.emit_signal.assert_not_called()

    def test_icon_name_matches_state(self, tray):
        tray.update_state("bad")

        # PropertiesChanged should carry the correct icon name
        props_call = tray._bus.emit_signal.call_args_list[1]
        variant = props_call[0][4]  # GLib.Variant argument (5th positional)
        # Unpack (sa{sv}as): interface, changed_props, invalidated
        iface, changed, invalidated = variant.unpack()
        assert iface == SNI_INTERFACE
        assert changed["IconName"] == "dorso-bad"

    def test_layout_updated_on_state_change(self, tray):
        """Changing state should also emit LayoutUpdated for the menu."""
        tray._current_state = "good"
        tray.update_state("bad")

        # Should have: NewIcon, PropertiesChanged, LayoutUpdated
        assert tray._bus.emit_signal.call_count == 3

    def test_same_state_no_layout_updated(self, tray):
        """Re-setting same state should NOT emit LayoutUpdated."""
        tray._current_state = "good"
        tray.update_state("good")

        # Should have only: NewIcon, PropertiesChanged (no LayoutUpdated)
        assert tray._bus.emit_signal.call_count == 2


class TestHandleClick:
    def test_toggle_callback(self, tray):
        tray._handle_click(1)
        tray._on_toggle.assert_called_once()

    def test_calibrate_callback(self, tray):
        tray._handle_click(2)
        tray._on_calibrate.assert_called_once()

    def test_analytics_callback(self, tray):
        tray._handle_click(3)
        tray._on_analytics.assert_called_once()

    def test_settings_callback(self, tray):
        tray._handle_click(4)
        tray._on_settings.assert_called_once()

    def test_quit_callback(self, tray):
        tray._handle_click(5)
        tray._on_quit.assert_called_once()

    def test_unknown_id_no_crash(self, tray):
        tray._handle_click(999)  # Should not raise
