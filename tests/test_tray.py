"""Unit tests for TrayIcon D-Bus signal emission."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from dorso.tray import SNI_INTERFACE, SNI_PATH, TrayIcon, _generate_fallback_icons


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


class TestGenerateFallbackIcons:
    def test_creates_all_icon_files(self):
        """Fallback icon generation should create 6 PNG files."""
        icon_dir = _generate_fallback_icons()
        expected = {"dorso-good.png", "dorso-bad.png", "dorso-away.png",
                    "dorso-paused.png", "dorso-calibrating.png", "dorso-disabled.png"}
        created = {f.name for f in icon_dir.iterdir()}
        assert expected == created


class TestSniProperties:
    def test_icon_name_reflects_state(self, tray):
        """SNI IconName property should match current state."""
        tray._current_state = "bad"
        result = tray._on_sni_prop(None, None, None, None, "IconName")
        assert result.unpack() == "dorso-bad"

    def test_category_is_application_status(self, tray):
        result = tray._on_sni_prop(None, None, None, None, "Category")
        assert result.unpack() == "ApplicationStatus"

    def test_item_is_menu(self, tray):
        result = tray._on_sni_prop(None, None, None, None, "ItemIsMenu")
        assert result.unpack() is True

    def test_unknown_property_returns_none(self, tray):
        result = tray._on_sni_prop(None, None, None, None, "NonExistent")
        assert result is None


class TestMenuProperties:
    def test_version(self, tray):
        result = tray._on_menu_prop(None, None, None, None, "Version")
        assert result.unpack() == 4

    def test_unknown_property_returns_none(self, tray):
        result = tray._on_menu_prop(None, None, None, None, "NonExistent")
        assert result is None


class TestStop:
    def test_stop_unregisters_objects(self, tray):
        """stop() should unregister D-Bus objects."""
        tray._menu_reg_id = 2
        tray._bus_name_id = 3

        with patch("dorso.tray.Gio"):
            tray.stop()

        tray._bus.unregister_object.assert_any_call(1)
        tray._bus.unregister_object.assert_any_call(2)

    def test_stop_without_bus_no_crash(self):
        """stop() with no bus should not raise."""
        icon = TrayIcon(
            on_toggle=MagicMock(), on_calibrate=MagicMock(),
            on_settings=MagicMock(), on_analytics=MagicMock(),
            on_quit=MagicMock(),
        )
        icon.stop()  # Should not raise
