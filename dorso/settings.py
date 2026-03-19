"""Settings management — TOML config in XDG_CONFIG_HOME."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomli_w

from dorso.models import (
    CalibrationData,
    DetectionMode,
    PostureConfig,
    WarningMode,
)
from dorso.overlay import DEFAULT_WARNING_COLOR


def _config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "dorso"


def _config_path() -> Path:
    return _config_dir() / "config.toml"


def is_first_launch() -> bool:
    """True if no config file exists yet (never been run before)."""
    return not _config_path().exists()


@dataclass
class Settings:
    """Application settings with auto-persistence."""

    warning_mode: WarningMode = WarningMode.GLOW
    detection_mode: DetectionMode = DetectionMode.RESPONSIVE
    intensity: float = 1.0
    slouch_sensitivity: float = 0.03
    warning_onset_delay: float = 0.0
    camera_id: int = 0
    warning_color: tuple[float, float, float] = DEFAULT_WARNING_COLOR
    calibration: CalibrationData | None = None

    def to_posture_config(self) -> PostureConfig:
        return PostureConfig(
            intensity=self.intensity,
            warning_onset_delay=self.warning_onset_delay,
            slouch_sensitivity=self.slouch_sensitivity,
        )

    def save(self) -> None:
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "warning_mode": self.warning_mode.value,
            "detection_mode": self.detection_mode.value,
            "intensity": self.intensity,
            "slouch_sensitivity": self.slouch_sensitivity,
            "warning_onset_delay": self.warning_onset_delay,
            "camera_id": self.camera_id,
            "warning_color": list(self.warning_color),
        }
        if self.calibration and self.calibration.is_valid:
            data["calibration"] = {
                "nose_y": self.calibration.nose_y,
                "face_width": self.calibration.face_width,
                "timestamp": self.calibration.timestamp,
            }

        path.write_bytes(tomli_w.dumps(data).encode())

    @classmethod
    def load(cls) -> Settings:
        path = _config_path()
        if not path.exists():
            return cls()

        try:
            data = tomllib.loads(path.read_text())
        except Exception:
            return cls()

        cal_data = data.get("calibration")
        calibration = None
        if isinstance(cal_data, dict):
            try:
                calibration = CalibrationData(
                    nose_y=float(cal_data["nose_y"]),
                    face_width=float(cal_data["face_width"]),
                    timestamp=float(cal_data.get("timestamp", 0)),
                )
            except (KeyError, ValueError, TypeError):
                pass

        try:
            warning_mode = WarningMode(data.get("warning_mode", "glow"))
        except ValueError:
            warning_mode = WarningMode.GLOW

        try:
            detection_mode = DetectionMode(data.get("detection_mode", "responsive"))
        except ValueError:
            detection_mode = DetectionMode.RESPONSIVE

        return cls(
            warning_mode=warning_mode,
            detection_mode=detection_mode,
            intensity=float(data.get("intensity", 1.0)),
            slouch_sensitivity=float(data.get("slouch_sensitivity", 0.03)),
            warning_onset_delay=float(data.get("warning_onset_delay", 0.0)),
            camera_id=int(data.get("camera_id", 0)),
            warning_color=tuple(data.get("warning_color", list(DEFAULT_WARNING_COLOR))),
            calibration=calibration,
        )
