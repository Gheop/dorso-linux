"""Core data types for dorso-linux."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto


class AppState(Enum):
    """Top-level application state."""

    DISABLED = auto()
    CALIBRATING = auto()
    MONITORING = auto()
    PAUSED = auto()


class PauseReason(Enum):
    """Why monitoring is paused."""

    NO_PROFILE = auto()
    CAMERA_DISCONNECTED = auto()
    SCREEN_LOCKED = auto()
    USER_PAUSED = auto()


class WarningMode(Enum):
    """Visual feedback style when slouching."""

    GLOW = "glow"
    BORDER = "border"
    SOLID = "solid"
    NONE = "none"


class DetectionMode(Enum):
    """Frame rate / CPU trade-off."""

    RESPONSIVE = "responsive"  # ~10 fps
    BALANCED = "balanced"  # ~4 fps
    PERFORMANCE = "performance"  # ~2 fps

    @property
    def base_interval(self) -> float:
        """Base interval in seconds between frames when posture is good."""
        return {
            DetectionMode.RESPONSIVE: 0.1,
            DetectionMode.BALANCED: 0.25,
            DetectionMode.PERFORMANCE: 0.5,
        }[self]

    @property
    def slouch_interval(self) -> float:
        """Interval when slouching (always fast for responsive feedback)."""
        return 0.1


@dataclass
class PostureReading:
    """A single posture measurement from a detector."""

    timestamp: float
    is_slouching: bool
    severity: float  # 0.0 (perfect) to 1.0 (very bad)
    face_detected: bool = True

    @staticmethod
    def no_face(timestamp: float | None = None) -> PostureReading:
        return PostureReading(
            timestamp=timestamp or time.time(),
            is_slouching=False,
            severity=0.0,
            face_detected=False,
        )


@dataclass
class CalibrationData:
    """Baseline posture measurements from calibration."""

    nose_y: float  # Normalized Y position of nose (0=top, 1=bottom)
    face_width: float  # Normalized face width (fraction of frame)
    timestamp: float = field(default_factory=time.time)

    @property
    def is_valid(self) -> bool:
        return self.nose_y > 0 and self.face_width > 0


@dataclass
class PostureConfig:
    """Tunable parameters for the posture engine."""

    slouch_frame_threshold: int = 8  # Consecutive bad frames to trigger warning
    good_frame_threshold: int = 5  # Consecutive good frames to clear warning
    warning_onset_delay: float = 0.0  # Seconds to wait before showing warning
    intensity: float = 1.0  # Warning intensity multiplier (0.5 = gentler, 2.0 = harsher)
    slouch_sensitivity: float = 0.03  # Nose Y drop threshold (normalized)
    away_frame_threshold: int = 30  # Frames without face before "away"
