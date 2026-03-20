"""Tests for CalibrationDialog.

GTK tests require a display (real or virtual via xvfb-run).
Non-GTK tests run everywhere.
"""

from __future__ import annotations

import numpy as np
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


# -- Non-GTK tests (run without display) --


class TestStartStopPreview:
    """Test preview subscription logic without requiring GTK display."""

    @pytest.mark.skipif(not _HAS_DISPLAY, reason="No display")
    def test_start_preview_subscribes(self):
        from dorso.calibration import CalibrationDialog

        hub = MagicMock()

        with patch.object(CalibrationDialog, "_ensure_landmarker"):
            with patch.object(CalibrationDialog, "__init__", lambda self, *a, **kw: None):
                dialog = CalibrationDialog.__new__(CalibrationDialog)
                dialog._hub = hub
                dialog._preview_subscribed = False
                dialog._landmarker = None
                dialog._landmarker_lock = __import__("threading").Lock()
                dialog._start_preview()

        assert dialog._preview_subscribed is True
        hub.subscribe.assert_called_once()

    @pytest.mark.skipif(not _HAS_DISPLAY, reason="No display")
    def test_stop_preview_unsubscribes_and_closes_landmarker(self):
        from dorso.calibration import CalibrationDialog

        hub = MagicMock()
        mock_landmarker = MagicMock()

        with patch.object(CalibrationDialog, "__init__", lambda self, *a, **kw: None):
            dialog = CalibrationDialog.__new__(CalibrationDialog)
            dialog._hub = hub
            dialog._preview_subscribed = True
            dialog._landmarker = mock_landmarker
            dialog._landmarker_lock = __import__("threading").Lock()
            dialog._stop_preview()

        hub.unsubscribe.assert_called_once_with("cal_preview")
        assert dialog._preview_subscribed is False
        mock_landmarker.close.assert_called_once()
        assert dialog._landmarker is None

    @pytest.mark.skipif(not _HAS_DISPLAY, reason="No display")
    def test_stop_preview_noop_when_not_subscribed(self):
        from dorso.calibration import CalibrationDialog

        hub = MagicMock()

        with patch.object(CalibrationDialog, "__init__", lambda self, *a, **kw: None):
            dialog = CalibrationDialog.__new__(CalibrationDialog)
            dialog._hub = hub
            dialog._preview_subscribed = False
            dialog._landmarker = None
            dialog._landmarker_lock = __import__("threading").Lock()
            dialog._stop_preview()

        hub.unsubscribe.assert_not_called()


class TestOnPreviewFrame:
    @pytest.mark.skipif(not _HAS_DISPLAY, reason="No display")
    def test_processes_frame(self):
        from dorso.calibration import CalibrationDialog

        with patch.object(CalibrationDialog, "__init__", lambda self, *a, **kw: None):
            dialog = CalibrationDialog.__new__(CalibrationDialog)
            dialog._landmarker = MagicMock()
            dialog._landmarker_lock = __import__("threading").Lock()

        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with patch("dorso.calibration.cv2") as mock_cv2, \
             patch("dorso.calibration.detect_and_draw", return_value=frame) as mock_draw, \
             patch("dorso.calibration.GLib") as mock_glib:
            mock_cv2.flip.return_value = frame
            mock_cv2.cvtColor.return_value = frame
            dialog._on_preview_frame(frame)

        mock_cv2.flip.assert_called_once()
        mock_draw.assert_called_once()
        mock_glib.idle_add.assert_called_once()


class TestEnsureLandmarker:
    @pytest.mark.skipif(not _HAS_DISPLAY, reason="No display")
    def test_already_exists_noop(self):
        from dorso.calibration import CalibrationDialog

        with patch.object(CalibrationDialog, "__init__", lambda self, *a, **kw: None):
            dialog = CalibrationDialog.__new__(CalibrationDialog)
            dialog._landmarker = MagicMock()  # already set

        with patch("dorso.calibration._model_path") as mock_path:
            dialog._ensure_landmarker()

        mock_path.assert_not_called()  # should have returned early

    @pytest.mark.skipif(not _HAS_DISPLAY, reason="No display")
    def test_creation_failure_sets_none(self):
        from dorso.calibration import CalibrationDialog

        with patch.object(CalibrationDialog, "__init__", lambda self, *a, **kw: None):
            dialog = CalibrationDialog.__new__(CalibrationDialog)
            dialog._landmarker = None

        with patch("dorso.calibration._model_path", side_effect=Exception("no model")):
            dialog._ensure_landmarker()

        assert dialog._landmarker is None
