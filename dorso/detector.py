"""Abstract base class for posture detectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from dorso.models import CalibrationData, PostureReading


class PostureDetector(ABC):
    """Interface for posture detection backends (camera, sensors, etc.)."""

    def __init__(self) -> None:
        self.on_reading: Callable[[PostureReading], None] | None = None

    @abstractmethod
    def start(self) -> None:
        """Start detection loop."""

    @abstractmethod
    def stop(self) -> None:
        """Stop detection loop and release resources."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the detection source is available (e.g. camera connected)."""

    @abstractmethod
    def is_active(self) -> bool:
        """Check if currently detecting."""

    @abstractmethod
    def calibrate(self, on_complete: Callable[[CalibrationData | None], None]) -> None:
        """Start calibration. Calls on_complete with data or None on failure."""

    @abstractmethod
    def set_interval(self, interval: float) -> None:
        """Set the interval between detection frames."""
