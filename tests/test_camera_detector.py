"""Unit tests for CameraDetector — logic only, no camera or MediaPipe."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from dorso.models import CalibrationData


@pytest.fixture
def mock_hub():
    hub = MagicMock()
    hub.is_available.return_value = True
    hub.dev_path = "/dev/video0"
    return hub


@pytest.fixture
def detector(mock_hub):
    """Create a CameraDetector with mocked landmarker creation."""
    from dorso.camera_detector import CameraDetector
    det = CameraDetector(hub=mock_hub, sensitivity=0.03)
    return det


class TestSensitivityProperty:
    def test_getter(self, detector):
        assert detector.sensitivity == 0.03

    def test_setter(self, detector):
        detector.sensitivity = 0.05
        assert detector.sensitivity == 0.05
        assert detector._sensitivity == 0.05


class TestProcessFrame:
    def test_no_face_returns_no_face_reading(self, detector):
        """When landmarks return (None, None), result should be no_face."""
        landmarker = MagicMock()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with patch.object(type(detector), "_extract_landmarks", return_value=(None, None)):
            reading = detector._process_frame(landmarker, frame)

        assert not reading.face_detected
        assert not reading.is_slouching
        assert reading.severity == 0.0

    def test_no_calibration_returns_not_slouching(self, detector):
        """Without calibration, should return face_detected=True, is_slouching=False."""
        landmarker = MagicMock()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with patch.object(type(detector), "_extract_landmarks", return_value=(0.5, 0.1)):
            reading = detector._process_frame(landmarker, frame)

        assert reading.face_detected
        assert not reading.is_slouching
        assert reading.severity == 0.0

    def test_slouching_detected(self, detector):
        """Nose Y drop beyond sensitivity threshold should trigger slouching."""
        detector._calibration = CalibrationData(nose_y=0.40, face_width=0.10)
        landmarker = MagicMock()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Nose at 0.50 = drop of 0.10 > sensitivity 0.03
        with patch.object(type(detector), "_extract_landmarks", return_value=(0.50, 0.10)):
            reading = detector._process_frame(landmarker, frame)

        assert reading.face_detected
        assert reading.is_slouching
        assert reading.severity > 0.0

    def test_good_posture(self, detector):
        """Nose at calibrated position should not trigger slouching."""
        detector._calibration = CalibrationData(nose_y=0.40, face_width=0.10)
        landmarker = MagicMock()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with patch.object(type(detector), "_extract_landmarks", return_value=(0.40, 0.10)):
            reading = detector._process_frame(landmarker, frame)

        assert reading.face_detected
        assert not reading.is_slouching
        assert reading.severity == 0.0

    def test_forward_head_boosts_severity(self, detector):
        """Face width increase > 5% should boost severity."""
        detector._calibration = CalibrationData(nose_y=0.40, face_width=0.10)
        landmarker = MagicMock()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Slouching + face 20% wider
        with patch.object(type(detector), "_extract_landmarks", return_value=(0.50, 0.12)):
            reading = detector._process_frame(landmarker, frame)

        assert reading.is_slouching
        assert reading.severity > 0.0


class TestSmoothingWindow:
    def test_smoothing_averages_frames(self, detector):
        """Multiple frames should be averaged via the smoothing window."""
        detector._calibration = CalibrationData(nose_y=0.40, face_width=0.10)
        landmarker = MagicMock()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Send 5 frames at the calibration nose_y
        for _ in range(5):
            with patch.object(type(detector), "_extract_landmarks", return_value=(0.40, 0.10)):
                reading = detector._process_frame(landmarker, frame)

        assert not reading.is_slouching

        # Now send one bad frame — smoothing should dampen it
        with patch.object(type(detector), "_extract_landmarks", return_value=(0.50, 0.10)):
            reading = detector._process_frame(landmarker, frame)

        # Average of [0.40, 0.40, 0.40, 0.40, 0.50] = 0.42
        # Drop = 0.42 - 0.40 = 0.02 < sensitivity 0.03
        assert not reading.is_slouching

    def test_smoothing_clears_on_no_face(self, detector):
        """Smoothing window should clear when no face is detected."""
        detector._smoothing_window.extend([0.40, 0.41, 0.42])
        landmarker = MagicMock()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with patch.object(type(detector), "_extract_landmarks", return_value=(None, None)):
            detector._process_frame(landmarker, frame)

        assert len(detector._smoothing_window) == 0


class TestStartStop:
    def test_start_subscribes_to_hub(self, detector, mock_hub):
        with patch.object(detector, "_ensure_landmarker"):
            detector.start()

        assert detector._running
        mock_hub.subscribe.assert_called_once()
        name, callback = mock_hub.subscribe.call_args[0][:2]
        assert name == "detector"

    def test_stop_unsubscribes_from_hub(self, detector, mock_hub):
        with patch.object(detector, "_ensure_landmarker"):
            detector.start()
        detector.stop()

        assert not detector._running
        mock_hub.unsubscribe.assert_called_once_with("detector")

    def test_start_twice_is_idempotent(self, detector, mock_hub):
        with patch.object(detector, "_ensure_landmarker"):
            detector.start()
            detector.start()

        assert mock_hub.subscribe.call_count == 1

    def test_stop_when_not_running_is_noop(self, detector, mock_hub):
        detector.stop()
        mock_hub.unsubscribe.assert_not_called()


class TestSetInterval:
    def test_set_interval_resubscribes_when_running(self, detector, mock_hub):
        with patch.object(detector, "_ensure_landmarker"):
            detector.start()

        detector.set_interval(0.5)  # 2 fps
        # subscribe called twice: start + set_interval
        assert mock_hub.subscribe.call_count == 2
        _, kwargs = mock_hub.subscribe.call_args
        assert kwargs.get("fps") == pytest.approx(2.0)

    def test_set_interval_stores_value_when_stopped(self, detector, mock_hub):
        detector.set_interval(0.5)
        assert detector._interval == 0.5
        mock_hub.subscribe.assert_not_called()


class TestCalibrate:
    def test_calibrate_starts_thread(self, detector):
        on_complete = MagicMock()
        with patch("dorso.camera_detector.threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            detector.calibrate(on_complete)
            mock_thread.assert_called_once()
            mock_thread.return_value.start.assert_called_once()
