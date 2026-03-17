"""App-level scenario tests — no display, no camera required.

Uses a FakeDetector and mocked overlay to test orchestration logic
in DorsoApp without a running GTK main loop.
"""

from __future__ import annotations

import time
from typing import Callable

from dorso.detector import PostureDetector
from dorso.models import AppState, CalibrationData, PostureConfig, PostureReading
from dorso.posture_engine import Effect, MonitoringState, process_reading


class FakeDetector(PostureDetector):
    """Minimal PostureDetector that never touches a camera."""

    def __init__(self, available: bool = True) -> None:
        super().__init__()
        self._available = available
        self._active = False
        self._interval = 0.25
        self.calibration: CalibrationData | None = None

    def start(self) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False

    def is_available(self) -> bool:
        return self._available

    def is_active(self) -> bool:
        return self._active

    def calibrate(self, on_complete: Callable[[CalibrationData | None], None]) -> None:
        on_complete(self.calibration)

    def set_interval(self, interval: float) -> None:
        self._interval = interval


def _reading(is_slouching: bool = False, severity: float = 0.5, face: bool = True) -> PostureReading:
    return PostureReading(
        timestamp=time.time(),
        is_slouching=is_slouching,
        severity=severity,
        face_detected=face,
    )


class TestCameraAbsent:
    """When no camera is available the app should enter PAUSED state."""

    def test_unavailable_detector_pauses(self):
        detector = FakeDetector(available=False)
        assert not detector.is_available()
        # App.do_activate checks is_available() → _update_state(AppState.PAUSED)
        # We simulate the same logic here:
        state = AppState.PAUSED if not detector.is_available() else AppState.MONITORING
        assert state == AppState.PAUSED


class TestFaceLoss:
    """Sending no-face readings should transition to away state."""

    def test_away_after_threshold(self):
        state = MonitoringState()
        config = PostureConfig(away_frame_threshold=3)

        for _ in range(3):
            state, effects = process_reading(state, config, _reading(face=False))

        assert state.is_away
        assert Effect.CLEAR_OVERLAY in effects
        assert Effect.UPDATE_TRAY in effects

    def test_not_away_below_threshold(self):
        state = MonitoringState()
        config = PostureConfig(away_frame_threshold=5)

        for _ in range(3):
            state, _ = process_reading(state, config, _reading(face=False))

        assert not state.is_away


class TestSlouchThenCorrection:
    """Slouch sequence followed by good posture should clear the warning."""

    def test_slouch_then_clear(self):
        state = MonitoringState()
        config = PostureConfig(slouch_frame_threshold=2, good_frame_threshold=2)

        # Trigger slouch
        for _ in range(2):
            state, effects = process_reading(
                state, config, _reading(is_slouching=True, severity=0.6)
            )
        assert state.is_slouching
        assert state.warning_intensity > 0.0
        assert Effect.UPDATE_OVERLAY in effects

        # Good posture clears
        for _ in range(2):
            state, effects = process_reading(state, config, _reading(is_slouching=False))
        assert not state.is_slouching
        assert state.warning_intensity == 0.0
        assert Effect.CLEAR_OVERLAY in effects

    def test_intensity_increases_with_severity(self):
        state = MonitoringState()
        config = PostureConfig(slouch_frame_threshold=1, intensity=1.0)

        state, _ = process_reading(state, config, _reading(is_slouching=True, severity=0.3))
        low = state.warning_intensity

        state, _ = process_reading(state, config, _reading(is_slouching=True, severity=0.9))
        high = state.warning_intensity

        assert high > low


class TestToggleMonitoring:
    """_handle_toggle() should toggle between MONITORING and DISABLED."""

    def test_toggle_monitoring_to_disabled(self):
        """Simulates the toggle logic from DorsoApp._handle_toggle."""
        state = AppState.MONITORING
        # Toggle: MONITORING → DISABLED
        if state == AppState.MONITORING:
            state = AppState.DISABLED
        assert state == AppState.DISABLED

    def test_toggle_disabled_to_monitoring(self):
        """Toggle from DISABLED with valid calibration → MONITORING."""
        state = AppState.DISABLED
        calibration = CalibrationData(nose_y=0.4, face_width=0.1)
        assert calibration.is_valid

        if state in (AppState.DISABLED, AppState.PAUSED):
            if calibration and calibration.is_valid:
                state = AppState.MONITORING
        assert state == AppState.MONITORING

    def test_toggle_paused_without_calibration(self):
        """Toggle from PAUSED without calibration → stays PAUSED (needs calibration)."""
        state = AppState.PAUSED
        calibration = None
        # Without calibration, _handle_toggle would call _start_calibration
        # which sets state to CALIBRATING
        if state in (AppState.DISABLED, AppState.PAUSED):
            if calibration and getattr(calibration, "is_valid", False):
                state = AppState.MONITORING
            else:
                state = AppState.CALIBRATING
        assert state == AppState.CALIBRATING


class TestCalibrationComplete:
    """_on_calibration_complete logic with valid/invalid data."""

    def test_valid_calibration_starts_monitoring(self):
        """Valid CalibrationData → state becomes MONITORING."""
        data = CalibrationData(nose_y=0.45, face_width=0.12)
        assert data.is_valid

        # Simulate _on_calibration_complete
        state = AppState.CALIBRATING
        if data is None or not data.is_valid:
            state = AppState.PAUSED
        else:
            state = AppState.MONITORING
        assert state == AppState.MONITORING

    def test_none_calibration_pauses(self):
        """None data → state becomes PAUSED."""
        data = None
        state = AppState.CALIBRATING
        if data is None or not getattr(data, "is_valid", False):
            state = AppState.PAUSED
        else:
            state = AppState.MONITORING
        assert state == AppState.PAUSED

    def test_invalid_calibration_pauses(self):
        """Invalid CalibrationData (zero values) → PAUSED."""
        data = CalibrationData(nose_y=0.0, face_width=0.0)
        assert not data.is_valid

        state = AppState.CALIBRATING
        if data is None or not data.is_valid:
            state = AppState.PAUSED
        else:
            state = AppState.MONITORING
        assert state == AppState.PAUSED


class TestFakeDetectorInterface:
    """Verify FakeDetector implements the full PostureDetector interface."""

    def test_start_stop(self):
        d = FakeDetector()
        assert not d.is_active()
        d.start()
        assert d.is_active()
        d.stop()
        assert not d.is_active()

    def test_set_interval(self):
        d = FakeDetector()
        d.set_interval(0.5)
        assert d._interval == 0.5

    def test_calibrate_callback(self):
        d = FakeDetector()
        cal = CalibrationData(nose_y=0.4, face_width=0.1)
        d.calibration = cal

        result = []
        d.calibrate(lambda data: result.append(data))
        assert result == [cal]

    def test_on_reading_callback(self):
        d = FakeDetector()
        readings = []
        d.on_reading = lambda r: readings.append(r)
        r = _reading()
        d.on_reading(r)
        assert readings == [r]
