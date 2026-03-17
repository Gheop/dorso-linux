"""Pure logic posture engine — no I/O, no side effects.

Port of PostureEngine.swift from the macOS dorso app.
All functions take state + input and return new state + effects.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, auto

from dorso.models import PostureConfig, PostureReading


class Effect(Enum):
    """Side effects requested by the engine (executed by app.py)."""

    UPDATE_OVERLAY = auto()
    UPDATE_TRAY = auto()
    CLEAR_OVERLAY = auto()


@dataclass
class MonitoringState:
    """Mutable state tracked by the posture engine."""

    consecutive_slouch_frames: int = 0
    consecutive_good_frames: int = 0
    consecutive_no_face_frames: int = 0
    is_slouching: bool = False
    is_away: bool = False
    bad_posture_start_time: float | None = None
    warning_intensity: float = 0.0  # 0.0 to 1.0


def process_reading(
    state: MonitoringState,
    config: PostureConfig,
    reading: PostureReading,
) -> tuple[MonitoringState, list[Effect]]:
    """Process a single posture reading. Returns (new_state, effects).

    This is the core algorithm:
    1. Track consecutive slouch/good frames
    2. Apply onset delay
    3. Calculate warning intensity via power function
    """
    effects: list[Effect] = []
    s = replace(state)

    # Handle no-face frames (away detection)
    if not reading.face_detected:
        s.consecutive_no_face_frames += 1
        if s.consecutive_no_face_frames >= config.away_frame_threshold and not s.is_away:
            s.is_away = True
            s.warning_intensity = 0.0
            s.is_slouching = False
            s.consecutive_slouch_frames = 0
            s.consecutive_good_frames = 0
            s.bad_posture_start_time = None
            effects.append(Effect.CLEAR_OVERLAY)
            effects.append(Effect.UPDATE_TRAY)
        return s, effects

    # Face detected — reset away state
    s.consecutive_no_face_frames = 0
    if s.is_away:
        s.is_away = False
        effects.append(Effect.UPDATE_TRAY)

    # Count consecutive frames
    if reading.is_slouching:
        s.consecutive_slouch_frames += 1
        s.consecutive_good_frames = 0
    else:
        s.consecutive_good_frames += 1
        s.consecutive_slouch_frames = 0

    # State transitions
    if not s.is_slouching:
        # Check if we should start warning
        if s.consecutive_slouch_frames >= config.slouch_frame_threshold:
            now = reading.timestamp
            if s.bad_posture_start_time is None:
                s.bad_posture_start_time = now

            elapsed = now - s.bad_posture_start_time
            if elapsed >= config.warning_onset_delay:
                s.is_slouching = True
                s.warning_intensity = _calculate_intensity(
                    reading.severity, config.intensity
                )
                effects.append(Effect.UPDATE_OVERLAY)
                effects.append(Effect.UPDATE_TRAY)
    else:
        # Currently slouching — update intensity or clear
        if s.consecutive_good_frames >= config.good_frame_threshold:
            # Good posture restored
            s.is_slouching = False
            s.warning_intensity = 0.0
            s.bad_posture_start_time = None
            effects.append(Effect.CLEAR_OVERLAY)
            effects.append(Effect.UPDATE_TRAY)
        else:
            # Still slouching — update intensity
            new_intensity = _calculate_intensity(
                reading.severity, config.intensity
            )
            if abs(new_intensity - s.warning_intensity) > 0.01:
                s.warning_intensity = new_intensity
                effects.append(Effect.UPDATE_OVERLAY)

    return s, effects


def process_screen_lock(
    state: MonitoringState, is_locked: bool
) -> tuple[MonitoringState, list[Effect]]:
    """Handle screen lock/unlock."""
    s = replace(state)
    effects: list[Effect] = []

    if is_locked:
        s.warning_intensity = 0.0
        s.is_slouching = False
        s.consecutive_slouch_frames = 0
        s.consecutive_good_frames = 0
        s.bad_posture_start_time = None
        effects.append(Effect.CLEAR_OVERLAY)
    # On unlock, just resume — engine will pick up from clean state

    effects.append(Effect.UPDATE_TRAY)
    return s, effects


def _calculate_intensity(severity: float, config_intensity: float) -> float:
    """Calculate warning intensity from severity using power function.

    Higher config_intensity makes the response harsher (reaches full
    intensity at lower severity values).
    """
    severity = max(0.0, min(1.0, severity))
    # Power function: severity^(1/intensity)
    # intensity=1.0 → linear, intensity=2.0 → harsher (square root curve)
    if config_intensity <= 0:
        return 0.0
    adjusted = severity ** (1.0 / config_intensity)
    return max(0.0, min(1.0, adjusted))
