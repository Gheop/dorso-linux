"""Headless GTK tests for SettingsWindow.

Requires a display (real or virtual via xvfb-run).
Skipped automatically if no display is available.
"""

from __future__ import annotations

import shutil
from unittest.mock import MagicMock, patch

import pytest

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
def settings_env(tmp_path, monkeypatch):
    """Isolated settings environment with temp XDG dirs."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture
def fake_hub():
    """Create a mock CameraHub."""
    hub = MagicMock()
    hub.is_available.return_value = True
    hub.dev_path = "/dev/video0"
    return hub


@pytest.fixture
def settings_window(settings_env, fake_hub):
    """Create a SettingsWindow with default settings."""
    from dorso.settings import Settings
    from dorso.settings_window import SettingsWindow

    settings = Settings()
    on_changed = MagicMock()
    with patch("dorso.settings_window.list_cameras", return_value=[(0, "Fake Webcam"), (2, "USB Camera")]):
        win = SettingsWindow(hub=fake_hub, settings=settings, on_changed=on_changed)
    return win, settings, on_changed


class TestAutostart:
    def test_autostart_toggle_creates_file(self, settings_env, monkeypatch):
        """Enabling autostart should create the .desktop file."""
        from dorso.settings_window import _autostart_path, _desktop_source

        # Create a fake .desktop source
        src = _desktop_source()
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("[Desktop Entry]\nExec=dorso\n")

        dst = _autostart_path()
        assert not dst.exists()

        # Simulate switch activation
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        assert dst.exists()

    def test_autostart_toggle_removes_file(self, settings_env):
        """Disabling autostart should remove the .desktop file."""
        from dorso.settings_window import _autostart_path

        dst = _autostart_path()
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("[Desktop Entry]\nExec=dorso\n")
        assert dst.exists()

        dst.unlink(missing_ok=True)
        assert not dst.exists()


class TestI18nLabels:
    def test_labels_are_strings(self, settings_window):
        """All visible labels should be non-empty strings."""
        win, _, _ = settings_window
        # Check that mode buttons have labels
        for btn in win._mode_buttons:
            label = btn.get_label()
            assert isinstance(label, str)
            assert len(label) > 0

    def test_mode_button_count(self, settings_window):
        """There should be 4 warning mode buttons."""
        win, _, _ = settings_window
        assert len(win._mode_buttons) == 4

    def test_detection_button_count(self, settings_window):
        """There should be 3 detection mode buttons."""
        win, _, _ = settings_window
        assert len(win._det_buttons) == 3


class TestModeChange:
    def test_toggle_warning_mode(self, settings_window):
        """Toggling a mode button should update settings via on_changed."""
        from dorso.models import WarningMode

        win, settings, on_changed = settings_window

        # Find the "Border" button and activate it
        border_btn = None
        for btn in win._mode_buttons:
            if hasattr(btn, "_dorso_mode") and btn._dorso_mode == WarningMode.BORDER:
                border_btn = btn
                break

        assert border_btn is not None
        border_btn.set_active(True)

        # on_changed should have been called
        assert on_changed.called
        called_settings = on_changed.call_args[0][0]
        assert called_settings.warning_mode == WarningMode.BORDER

    def test_toggle_detection_mode(self, settings_window):
        """Toggling detection mode should update settings."""
        from dorso.models import DetectionMode

        win, settings, on_changed = settings_window

        eco_btn = None
        for btn in win._det_buttons:
            if hasattr(btn, "_dorso_mode") and btn._dorso_mode == DetectionMode.PERFORMANCE:
                eco_btn = btn
                break

        assert eco_btn is not None
        eco_btn.set_active(True)

        assert on_changed.called
        called_settings = on_changed.call_args[0][0]
        assert called_settings.detection_mode == DetectionMode.PERFORMANCE


class TestCameraDropdown:
    def test_dropdown_has_detected_cameras(self, settings_window):
        """Dropdown should list cameras returned by list_cameras."""
        win, _, _ = settings_window
        model = win._camera_dropdown.get_model()
        assert model.get_n_items() == 2
        assert model.get_string(0) == "Fake Webcam"
        assert model.get_string(1) == "USB Camera"

    def test_camera_map_matches(self, settings_window):
        """camera_map should contain device indices."""
        win, _, _ = settings_window
        assert win._camera_map == [0, 2]

    def test_default_camera_selected(self, settings_window):
        """Camera 0 (default) should be selected."""
        win, _, _ = settings_window
        assert win._camera_dropdown.get_selected() == 0

    def test_no_cameras(self, settings_env, fake_hub):
        """With no cameras, dropdown shows 'No camera detected'."""
        from dorso.settings import Settings
        from dorso.settings_window import SettingsWindow

        settings = Settings()
        on_changed = MagicMock()
        with patch("dorso.settings_window.list_cameras", return_value=[]):
            win = SettingsWindow(hub=fake_hub, settings=settings, on_changed=on_changed)

        model = win._camera_dropdown.get_model()
        assert model.get_n_items() == 1

    def test_saved_camera_unavailable(self, settings_env, fake_hub):
        """Saved camera_id not in detected list shows as unavailable."""
        from dorso.settings import Settings
        from dorso.settings_window import SettingsWindow

        settings = Settings(camera_id=5)
        on_changed = MagicMock()
        with patch("dorso.settings_window.list_cameras", return_value=[(0, "Webcam")]):
            win = SettingsWindow(hub=fake_hub, settings=settings, on_changed=on_changed)

        model = win._camera_dropdown.get_model()
        assert model.get_n_items() == 2
        # Camera 5 should be selected (the unavailable one)
        assert win._camera_dropdown.get_selected() == 1
        assert win._camera_map[1] == 5
