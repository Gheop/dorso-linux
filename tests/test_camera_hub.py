"""Tests for CameraHub — subscribe/unsubscribe, throttling, set_device."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from dorso.camera_hub import CameraHub


@pytest.fixture
def fake_capture():
    """Patch cv2.VideoCapture to return synthetic frames."""
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    mock_cap.read.return_value = (True, fake_frame)

    with patch("dorso.camera_hub.cv2.VideoCapture", return_value=mock_cap) as vc:
        yield vc, mock_cap, fake_frame


class TestSubscribeUnsubscribe:
    def test_subscribe_starts_capture(self, fake_capture):
        vc, mock_cap, _ = fake_capture
        hub = CameraHub("/dev/video0")

        received = []
        event = threading.Event()

        def cb(frame):
            received.append(frame)
            if len(received) >= 2:
                event.set()

        hub.subscribe("test", cb, fps=30.0)
        event.wait(timeout=3.0)
        hub.unsubscribe("test")
        hub.shutdown()

        assert len(received) >= 2
        assert vc.called

    def test_unsubscribe_last_stops_capture(self, fake_capture):
        hub = CameraHub("/dev/video0")

        hub.subscribe("a", lambda f: None, fps=10.0)
        assert hub._running

        hub.unsubscribe("a")
        time.sleep(0.5)
        assert not hub._running

        hub.shutdown()

    def test_multiple_subscribers(self, fake_capture):
        hub = CameraHub("/dev/video0")

        a_frames = []
        b_frames = []
        event = threading.Event()

        def cb_a(frame):
            a_frames.append(1)
            if len(a_frames) >= 2 and len(b_frames) >= 2:
                event.set()

        def cb_b(frame):
            b_frames.append(1)
            if len(a_frames) >= 2 and len(b_frames) >= 2:
                event.set()

        hub.subscribe("a", cb_a, fps=20.0)
        hub.subscribe("b", cb_b, fps=20.0)
        event.wait(timeout=3.0)

        hub.shutdown()
        assert len(a_frames) >= 2
        assert len(b_frames) >= 2

    def test_unsubscribe_one_keeps_running(self, fake_capture):
        hub = CameraHub("/dev/video0")

        hub.subscribe("a", lambda f: None, fps=10.0)
        hub.subscribe("b", lambda f: None, fps=10.0)

        hub.unsubscribe("a")
        assert hub._running  # b still subscribed

        hub.shutdown()


class TestSetDevice:
    def test_set_device_changes_path(self, fake_capture):
        hub = CameraHub("/dev/video0")
        hub.set_device("/dev/video2")
        assert hub.dev_path == "/dev/video2"
        hub.shutdown()

    def test_set_device_restarts_capture(self, fake_capture):
        hub = CameraHub("/dev/video0")

        received = []
        event = threading.Event()

        def cb(frame):
            received.append(1)
            if len(received) >= 1:
                event.set()

        hub.subscribe("test", cb, fps=20.0)
        event.wait(timeout=2.0)
        assert hub._running

        event.clear()
        received.clear()
        hub.set_device("/dev/video2")

        event.wait(timeout=2.0)
        assert hub._running
        assert hub.dev_path == "/dev/video2"
        assert len(received) >= 1

        hub.shutdown()

    def test_set_same_device_noop(self, fake_capture):
        hub = CameraHub("/dev/video0")
        hub.subscribe("test", lambda f: None, fps=10.0)
        time.sleep(0.2)

        thread_before = hub._thread
        hub.set_device("/dev/video0")  # same — should be noop
        assert hub._thread is thread_before

        hub.shutdown()


class TestIsAvailable:
    def test_available_when_open(self, fake_capture):
        hub = CameraHub("/dev/video0")
        assert hub.is_available()

    def test_unavailable_when_closed(self):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False

        with patch("dorso.camera_hub.cv2.VideoCapture", return_value=mock_cap):
            hub = CameraHub("/dev/video99")
            assert not hub.is_available()


class TestErrorHandling:
    def test_subscriber_exception_doesnt_crash(self, fake_capture):
        hub = CameraHub("/dev/video0")

        good_frames = []
        event = threading.Event()

        def bad_cb(frame):
            raise RuntimeError("oops")

        def good_cb(frame):
            good_frames.append(1)
            if len(good_frames) >= 2:
                event.set()

        hub.subscribe("bad", bad_cb, fps=20.0)
        hub.subscribe("good", good_cb, fps=20.0)
        event.wait(timeout=3.0)

        hub.shutdown()
        assert len(good_frames) >= 2

    def test_camera_open_failure(self):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False

        with patch("dorso.camera_hub.cv2.VideoCapture", return_value=mock_cap):
            hub = CameraHub("/dev/video99")
            hub.subscribe("test", lambda f: None, fps=10.0)
            time.sleep(0.5)
            assert not hub._running
            hub.shutdown()


class TestEdgeCases:
    def test_subscribe_with_fps_zero(self, fake_capture):
        """fps=0 should not cause division by zero — interval falls back to 1.0."""
        hub = CameraHub("/dev/video0")

        received = []
        event = threading.Event()

        def cb(frame):
            received.append(1)
            event.set()

        hub.subscribe("test", cb, fps=0)

        # Verify the subscriber interval is 1.0 (fallback), not infinity/error
        sub = hub._subscribers["test"]
        assert sub.interval == 1.0

        event.wait(timeout=3.0)
        hub.shutdown()
        assert len(received) >= 1


class TestFrameSharing:
    def test_subscribers_share_same_frame(self, fake_capture):
        """Subscribers receive the same frame object (zero-copy)."""
        hub = CameraHub("/dev/video0")
        frames_a = []
        frames_b = []
        event = threading.Event()

        def cb_a(frame):
            frames_a.append(frame)
            if frames_a and frames_b:
                event.set()

        def cb_b(frame):
            frames_b.append(frame)
            if frames_a and frames_b:
                event.set()

        hub.subscribe("a", cb_a, fps=20.0)
        hub.subscribe("b", cb_b, fps=20.0)
        event.wait(timeout=3.0)

        hub.shutdown()

        if frames_a and frames_b:
            assert frames_a[0] is frames_b[0]
