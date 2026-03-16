"""Tests for the pure logic posture engine."""

import time

from dorso.models import PostureConfig, PostureReading
from dorso.posture_engine import Effect, MonitoringState, process_reading, process_screen_lock


def _reading(is_slouching: bool = False, severity: float = 0.5, face: bool = True) -> PostureReading:
    return PostureReading(
        timestamp=time.time(),
        is_slouching=is_slouching,
        severity=severity,
        face_detected=face,
    )


def _default_config(**overrides) -> PostureConfig:
    return PostureConfig(**overrides)


class TestSlouchDetection:
    def test_no_warning_below_threshold(self):
        """Should not warn until consecutive slouch frames reach threshold."""
        state = MonitoringState()
        config = _default_config(slouch_frame_threshold=3)

        # 2 slouch frames — not enough
        for _ in range(2):
            state, effects = process_reading(state, config, _reading(is_slouching=True))
        assert not state.is_slouching
        assert state.warning_intensity == 0.0

    def test_warning_after_threshold(self):
        """Should start warning after enough consecutive slouch frames."""
        state = MonitoringState()
        config = _default_config(slouch_frame_threshold=3)

        for _ in range(3):
            state, effects = process_reading(state, config, _reading(is_slouching=True, severity=0.6))

        assert state.is_slouching
        assert state.warning_intensity > 0.0
        assert Effect.UPDATE_OVERLAY in effects
        assert Effect.UPDATE_TRAY in effects

    def test_clear_after_good_frames(self):
        """Should clear warning after enough consecutive good frames."""
        state = MonitoringState()
        config = _default_config(slouch_frame_threshold=2, good_frame_threshold=2)

        # Trigger slouch
        for _ in range(2):
            state, _ = process_reading(state, config, _reading(is_slouching=True, severity=0.5))
        assert state.is_slouching

        # Good frames to clear
        for _ in range(2):
            state, effects = process_reading(state, config, _reading(is_slouching=False))
        assert not state.is_slouching
        assert state.warning_intensity == 0.0
        assert Effect.CLEAR_OVERLAY in effects

    def test_single_good_frame_doesnt_clear(self):
        """A single good frame shouldn't clear the warning."""
        state = MonitoringState()
        config = _default_config(slouch_frame_threshold=2, good_frame_threshold=3)

        for _ in range(2):
            state, _ = process_reading(state, config, _reading(is_slouching=True, severity=0.5))
        assert state.is_slouching

        state, _ = process_reading(state, config, _reading(is_slouching=False))
        assert state.is_slouching  # Still slouching

    def test_intensity_updates_while_slouching(self):
        """Intensity should update when severity changes during slouch."""
        state = MonitoringState()
        config = _default_config(slouch_frame_threshold=2)

        for _ in range(2):
            state, _ = process_reading(state, config, _reading(is_slouching=True, severity=0.3))

        old_intensity = state.warning_intensity

        # Higher severity
        state, effects = process_reading(state, config, _reading(is_slouching=True, severity=0.9))
        assert state.warning_intensity > old_intensity
        assert Effect.UPDATE_OVERLAY in effects

    def test_onset_delay(self):
        """Warning should be delayed by onset_delay seconds."""
        now = time.time()
        state = MonitoringState()
        config = _default_config(slouch_frame_threshold=2, warning_onset_delay=1.0)

        # Send readings with same timestamp (not enough delay)
        for _ in range(3):
            r = PostureReading(timestamp=now, is_slouching=True, severity=0.5)
            state, _ = process_reading(state, config, r)

        # Should not be slouching yet (onset delay not met)
        # The delay starts from when threshold is first crossed
        # All readings at same timestamp, so 0 elapsed time
        assert not state.is_slouching

        # Now send with enough time passed
        r = PostureReading(timestamp=now + 1.5, is_slouching=True, severity=0.5)
        state, effects = process_reading(state, config, r)
        assert state.is_slouching


class TestAwayDetection:
    def test_away_after_no_face_threshold(self):
        """Should mark as away after enough no-face frames."""
        state = MonitoringState()
        config = _default_config(away_frame_threshold=3)

        for _ in range(3):
            state, effects = process_reading(state, config, _reading(face=False))

        assert state.is_away
        assert Effect.CLEAR_OVERLAY in effects
        assert Effect.UPDATE_TRAY in effects

    def test_not_away_below_threshold(self):
        state = MonitoringState()
        config = _default_config(away_frame_threshold=5)

        for _ in range(3):
            state, _ = process_reading(state, config, _reading(face=False))

        assert not state.is_away

    def test_return_from_away(self):
        state = MonitoringState()
        config = _default_config(away_frame_threshold=2)

        for _ in range(2):
            state, _ = process_reading(state, config, _reading(face=False))
        assert state.is_away

        state, effects = process_reading(state, config, _reading(face=True))
        assert not state.is_away
        assert Effect.UPDATE_TRAY in effects

    def test_slouch_warning_cleared_when_away(self):
        """Going away should clear any active slouch warning."""
        state = MonitoringState()
        config = _default_config(slouch_frame_threshold=2, away_frame_threshold=2)

        # Trigger slouch
        for _ in range(2):
            state, _ = process_reading(state, config, _reading(is_slouching=True, severity=0.5))
        assert state.is_slouching

        # Go away
        for _ in range(2):
            state, effects = process_reading(state, config, _reading(face=False))
        assert state.is_away
        assert not state.is_slouching
        assert state.warning_intensity == 0.0


class TestScreenLock:
    def test_lock_clears_state(self):
        state = MonitoringState()
        state.is_slouching = True
        state.warning_intensity = 0.8
        state.consecutive_slouch_frames = 10

        state, effects = process_screen_lock(state, is_locked=True)
        assert not state.is_slouching
        assert state.warning_intensity == 0.0
        assert state.consecutive_slouch_frames == 0
        assert Effect.CLEAR_OVERLAY in effects

    def test_unlock_emits_tray_update(self):
        state = MonitoringState()
        state, effects = process_screen_lock(state, is_locked=False)
        assert Effect.UPDATE_TRAY in effects


class TestIntensity:
    def test_zero_severity_zero_intensity(self):
        state = MonitoringState()
        config = _default_config(slouch_frame_threshold=1)

        state, _ = process_reading(state, config, _reading(is_slouching=True, severity=0.0))
        assert state.warning_intensity == 0.0

    def test_max_severity_max_intensity(self):
        state = MonitoringState()
        config = _default_config(slouch_frame_threshold=1, intensity=1.0)

        state, _ = process_reading(state, config, _reading(is_slouching=True, severity=1.0))
        assert state.warning_intensity == 1.0

    def test_higher_config_intensity_is_harsher(self):
        """Higher intensity config should produce higher warning for same severity."""
        config_gentle = _default_config(slouch_frame_threshold=1, intensity=0.5)
        config_harsh = _default_config(slouch_frame_threshold=1, intensity=2.0)

        state1 = MonitoringState()
        state1, _ = process_reading(state1, config_gentle, _reading(is_slouching=True, severity=0.3))

        state2 = MonitoringState()
        state2, _ = process_reading(state2, config_harsh, _reading(is_slouching=True, severity=0.3))

        assert state2.warning_intensity > state1.warning_intensity


class TestCounterReset:
    def test_good_frame_resets_slouch_counter(self):
        state = MonitoringState()
        config = _default_config(slouch_frame_threshold=5)

        for _ in range(3):
            state, _ = process_reading(state, config, _reading(is_slouching=True))
        assert state.consecutive_slouch_frames == 3

        state, _ = process_reading(state, config, _reading(is_slouching=False))
        assert state.consecutive_slouch_frames == 0
        assert state.consecutive_good_frames == 1

    def test_slouch_frame_resets_good_counter(self):
        state = MonitoringState()
        config = _default_config()

        for _ in range(3):
            state, _ = process_reading(state, config, _reading(is_slouching=False))
        assert state.consecutive_good_frames == 3

        state, _ = process_reading(state, config, _reading(is_slouching=True))
        assert state.consecutive_good_frames == 0
