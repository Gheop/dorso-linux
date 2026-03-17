"""Headless GTK tests for OnboardingWindow.

Requires a display (real or virtual via xvfb-run).
Skipped automatically if no display is available.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

# Skip entire module if GTK cannot initialize (no display)
try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gtk  # noqa: F401
    # Try to get a display — will fail without xvfb
    _display = __import__("gi.repository", fromlist=["Gdk"]).Gdk.Display.get_default()
    if _display is None:
        raise RuntimeError("No display")
    _HAS_DISPLAY = True
except Exception:
    _HAS_DISPLAY = False

pytestmark = pytest.mark.skipif(not _HAS_DISPLAY, reason="No display available (run with xvfb-run)")


@pytest.fixture
def fake_detector():
    """A mock detector that doesn't touch any camera."""
    detector = MagicMock()
    detector.is_available.return_value = True
    return detector


@pytest.fixture
def onboarding(fake_detector):
    """Create an OnboardingWindow with mocked camera preview."""
    from dorso.onboarding import OnboardingWindow

    on_complete = MagicMock()

    with patch.object(OnboardingWindow, "_start_preview"):
        win = OnboardingWindow(
            detector=fake_detector,
            camera_id=0,
            on_complete=on_complete,
        )
    return win, on_complete


class TestOnboardingPages:
    def test_stack_has_three_pages(self, onboarding):
        """The wizard should have exactly 3 pages: welcome, camera, done."""
        win, _ = onboarding
        stack = win._stack

        pages = []
        child = stack.get_first_child()
        while child is not None:
            name = stack.get_page(child).get_name()
            pages.append(name)
            child = child.get_next_sibling()

        assert len(pages) == 3
        assert "welcome" in pages
        assert "camera" in pages
        assert "done" in pages

    def test_initial_page_is_welcome(self, onboarding):
        """On creation, the visible page should be 'welcome'."""
        win, _ = onboarding
        assert win._stack.get_visible_child_name() == "welcome"


class TestOnboardingNavigation:
    def test_go_to_camera(self, onboarding):
        """_go_to_camera() should switch to the camera page."""
        win, _ = onboarding
        with patch.object(win, "_start_preview"):
            win._go_to_camera()
        assert win._stack.get_visible_child_name() == "camera"

    def test_go_to_done(self, onboarding):
        """_go_to_done() should switch to the done page."""
        win, _ = onboarding
        with patch.object(win, "_stop_preview"):
            win._go_to_done()
        assert win._stack.get_visible_child_name() == "done"


class TestCameraError:
    def test_camera_error_disables_calibrate_button(self, onboarding):
        """_show_camera_error() should disable the calibrate button."""
        win, _ = onboarding
        win._show_camera_error()
        assert not win._cal_btn.get_sensitive()


class TestCalibrationResult:
    def test_successful_calibration_goes_to_done(self, onboarding):
        """Valid calibration data should navigate to the 'done' page."""
        from dorso.models import CalibrationData

        win, _ = onboarding
        data = CalibrationData(nose_y=0.45, face_width=0.12)

        with patch.object(win, "_stop_preview"), patch.object(win, "_start_preview"):
            win._handle_calibration_result(data)

        assert win._stack.get_visible_child_name() == "done"

    def test_failed_calibration_stays_on_camera(self, onboarding):
        """None calibration data should stay on camera page with re-enabled button."""
        win, _ = onboarding
        with patch.object(win, "_start_preview"):
            win._go_to_camera()

        with patch.object(win, "_start_preview"):
            win._handle_calibration_result(None)

        assert win._stack.get_visible_child_name() == "camera"
        assert win._cal_btn.get_sensitive()


class TestSkip:
    def test_skip_calls_on_complete_with_none(self, onboarding):
        """Clicking skip should call on_complete(None)."""
        win, on_complete = onboarding

        with patch.object(win, "_stop_preview"):
            win._on_skip(MagicMock())

        on_complete.assert_called_once_with(None)
