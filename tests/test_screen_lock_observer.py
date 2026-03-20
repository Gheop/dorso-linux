"""Tests for ScreenLockObserver — graceful handling of missing dbus."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dorso.screen_lock_observer import ScreenLockObserver


class TestScreenLockObserver:
    def test_stop_without_start_no_crash(self):
        """stop() before start() should be a safe no-op."""
        cb = MagicMock()
        observer = ScreenLockObserver(on_lock_changed=cb)
        assert observer._bus is None
        assert observer._system_bus is None

        observer.stop()  # should not raise

        assert observer._bus is None
        assert observer._system_bus is None

    def test_start_with_dbus_unavailable(self):
        """If dbus import fails, start() should log a warning, not crash."""
        cb = MagicMock()
        observer = ScreenLockObserver(on_lock_changed=cb)

        with patch.dict("sys.modules", {"dbus": None, "dbus.mainloop.glib": None}):
            observer.start()  # should not raise

        assert observer._bus is None

    def test_stop_closes_buses(self):
        """stop() should close both buses and set them to None."""
        cb = MagicMock()
        observer = ScreenLockObserver(on_lock_changed=cb)

        mock_bus = MagicMock()
        mock_system_bus = MagicMock()
        observer._bus = mock_bus
        observer._system_bus = mock_system_bus

        observer.stop()

        mock_bus.close.assert_called_once()
        mock_system_bus.close.assert_called_once()
        assert observer._bus is None
        assert observer._system_bus is None
