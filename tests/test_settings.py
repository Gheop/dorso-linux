"""Tests for settings load/save."""

import os
import tempfile

from dorso.models import CalibrationData, DetectionMode, WarningMode
from dorso.settings import Settings


def test_defaults():
    s = Settings()
    assert s.warning_mode == WarningMode.GLOW
    assert s.detection_mode == DetectionMode.RESPONSIVE
    assert s.intensity == 1.0
    assert s.calibration is None


def test_round_trip(tmp_path, monkeypatch):
    """Save and reload should preserve all settings."""
    config_dir = tmp_path / "dorso"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    s = Settings(
        warning_mode=WarningMode.BORDER,
        detection_mode=DetectionMode.BALANCED,
        intensity=1.5,
        dead_zone=0.02,
        slouch_sensitivity=0.05,
        warning_onset_delay=0.5,
        blur_when_away=True,
        camera_id=2,
        calibration=CalibrationData(nose_y=0.45, face_width=0.12, timestamp=1000.0),
    )
    s.save()

    loaded = Settings.load()
    assert loaded.warning_mode == WarningMode.BORDER
    assert loaded.detection_mode == DetectionMode.BALANCED
    assert loaded.intensity == 1.5
    assert loaded.dead_zone == 0.02
    assert loaded.slouch_sensitivity == 0.05
    assert loaded.warning_onset_delay == 0.5
    assert loaded.blur_when_away is True
    assert loaded.camera_id == 2
    assert loaded.calibration is not None
    assert abs(loaded.calibration.nose_y - 0.45) < 0.001
    assert abs(loaded.calibration.face_width - 0.12) < 0.001


def test_load_missing_file(tmp_path, monkeypatch):
    """Loading from non-existent file should return defaults."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    s = Settings.load()
    assert s.warning_mode == WarningMode.GLOW
    assert s.calibration is None


def test_load_corrupt_file(tmp_path, monkeypatch):
    """Corrupt config file should return defaults."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config_dir = tmp_path / "dorso"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("this is not valid toml {{{")

    s = Settings.load()
    assert s.warning_mode == WarningMode.GLOW


def test_posture_config_from_settings():
    s = Settings(intensity=2.0, slouch_sensitivity=0.05, warning_onset_delay=1.0)
    config = s.to_posture_config()
    assert config.intensity == 2.0
    assert config.slouch_sensitivity == 0.05
    assert config.warning_onset_delay == 1.0
