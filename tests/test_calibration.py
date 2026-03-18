"""Headless GTK tests for CalibrationDialog.

Requires a display (real or virtual via xvfb-run).
Skipped automatically if no display is available.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

# Skip entire module if GTK cannot initialize (no display)
try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gtk  # noqa: F401
    _display = __import__("gi.repository", fromlist=["Gdk"]).Gdk.Display.get_default()
    if _display is None:
        raise RuntimeError("No display")
    _HAS_DISPLAY = True
except Exception:
    _HAS_DISPLAY = False

pytestmark = pytest.mark.skipif(not _HAS_DISPLAY, reason="No display available (run with xvfb-run)")


@pytest.fixture
def fake_hub():
    hub = MagicMock()
    hub.is_available.return_value = True
    hub.dev_path = "/dev/video0"
    return hub


@pytest.fixture
def fake_detector():
    detector = MagicMock()
    detector.is_available.return_value = True
    return detector


@pytest.fixture
def calibration_dialog(fake_hub, fake_detector):
    """Create a CalibrationDialog with mocked preview."""
    from dorso.calibration import CalibrationDialog

    on_complete = MagicMock()

    with patch.object(CalibrationDialog, "_start_preview"):
        dialog = CalibrationDialog(
            hub=fake_hub,
            detector=fake_detector,
            on_complete=on_complete,
        )
    return dialog, on_complete, fake_hub, fake_detector


class TestDialogCreation:
    def test_window_exists(self, calibration_dialog):
        dialog, _, _, _ = calibration_dialog
        assert dialog._window is not None

    def test_calibrate_button_enabled(self, calibration_dialog):
        dialog, _, _, _ = calibration_dialog
        assert dialog._calibrate_btn.get_sensitive()

    def test_cancel_button_enabled(self, calibration_dialog):
        dialog, _, _, _ = calibration_dialog
        assert dialog._cancel_btn.get_sensitive()


class TestCalibrationFlow:
    def test_on_calibrate_disables_buttons_and_starts(self, calibration_dialog):
        dialog, _, _, fake_detector = calibration_dialog

        with patch.object(dialog, "_stop_preview"):
            dialog._on_calibrate(MagicMock())

        assert not dialog._calibrate_btn.get_sensitive()
        assert not dialog._cancel_btn.get_sensitive()
        assert dialog._spinner.get_spinning()
        fake_detector.calibrate.assert_called_once()

    def test_finish_calls_on_complete(self, calibration_dialog):
        from dorso.models import CalibrationData

        dialog, on_complete, _, _ = calibration_dialog
        data = CalibrationData(nose_y=0.45, face_width=0.12)

        with patch.object(dialog, "_stop_preview"):
            dialog._finish(data)

        on_complete.assert_called_once_with(data)

    def test_finish_with_none(self, calibration_dialog):
        dialog, on_complete, _, _ = calibration_dialog

        with patch.object(dialog, "_stop_preview"):
            dialog._finish(None)

        on_complete.assert_called_once_with(None)


class TestCancel:
    def test_cancel_calls_on_complete_with_none(self, calibration_dialog):
        dialog, on_complete, _, _ = calibration_dialog

        with patch.object(dialog, "_stop_preview"):
            dialog._on_cancel(MagicMock())

        on_complete.assert_called_once_with(None)
