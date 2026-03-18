"""Tests for V4L2 camera enumeration (mocked filesystem + ioctl)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dorso.v4l2_cameras import list_cameras

# All tests mock _is_primary_node to avoid reading /sys
_PRIMARY = patch("dorso.v4l2_cameras._is_primary_node", return_value=True)


class TestListCameras:
    @patch("dorso.v4l2_cameras._SYS_VIDEO")
    def test_no_sys_video(self, mock_sys):
        """No /sys/class/video4linux → empty list."""
        mock_sys.exists.return_value = False
        assert list_cameras() == []

    @_PRIMARY
    @patch("dorso.v4l2_cameras._is_capture_device", return_value=True)
    @patch("dorso.v4l2_cameras._read_device_name", return_value="Integrated Camera")
    @patch("dorso.v4l2_cameras.os.path.exists", return_value=True)
    @patch("dorso.v4l2_cameras._SYS_VIDEO")
    def test_single_camera(self, mock_sys, mock_exists, mock_name, mock_capture, mock_primary):
        """Single video0 device → [(0, 'Integrated Camera')]."""
        entry = MagicMock()
        entry.name = "video0"
        mock_sys.exists.return_value = True
        mock_sys.iterdir.return_value = [entry]

        result = list_cameras()
        assert result == [(0, "Integrated Camera")]

    @_PRIMARY
    @patch("dorso.v4l2_cameras._is_capture_device")
    @patch("dorso.v4l2_cameras._read_device_name")
    @patch("dorso.v4l2_cameras.os.path.exists", return_value=True)
    @patch("dorso.v4l2_cameras._SYS_VIDEO")
    def test_filters_non_capture(self, mock_sys, mock_exists, mock_name, mock_capture, mock_primary):
        """Non-capture devices (metadata nodes) should be filtered out."""
        entry0 = MagicMock()
        entry0.name = "video0"
        entry1 = MagicMock()
        entry1.name = "video1"
        mock_sys.exists.return_value = True
        mock_sys.iterdir.return_value = [entry0, entry1]

        mock_capture.side_effect = lambda dev: dev == "/dev/video0"
        mock_name.return_value = "Webcam"

        result = list_cameras()
        assert result == [(0, "Webcam")]

    @_PRIMARY
    @patch("dorso.v4l2_cameras._is_capture_device", return_value=True)
    @patch("dorso.v4l2_cameras._read_device_name")
    @patch("dorso.v4l2_cameras.os.path.exists", return_value=True)
    @patch("dorso.v4l2_cameras._SYS_VIDEO")
    def test_multiple_cameras_sorted(self, mock_sys, mock_exists, mock_name, mock_capture, mock_primary):
        """Multiple cameras should be returned sorted by index."""
        entry2 = MagicMock()
        entry2.name = "video2"
        entry0 = MagicMock()
        entry0.name = "video0"
        mock_sys.exists.return_value = True
        mock_sys.iterdir.return_value = [entry2, entry0]

        mock_name.side_effect = lambda n: "USB Cam" if n == "video2" else "Built-in"

        result = list_cameras()
        assert result == [(0, "Built-in"), (2, "USB Cam")]

    @_PRIMARY
    @patch("dorso.v4l2_cameras._is_capture_device", return_value=True)
    @patch("dorso.v4l2_cameras._read_device_name", return_value="Cam")
    @patch("dorso.v4l2_cameras.os.path.exists", return_value=True)
    @patch("dorso.v4l2_cameras._SYS_VIDEO")
    def test_ignores_non_video_entries(self, mock_sys, mock_exists, mock_name, mock_capture, mock_primary):
        """Entries not starting with 'video' should be ignored."""
        entry_ok = MagicMock()
        entry_ok.name = "video0"
        entry_bad = MagicMock()
        entry_bad.name = "vbi0"
        mock_sys.exists.return_value = True
        mock_sys.iterdir.return_value = [entry_ok, entry_bad]

        result = list_cameras()
        assert result == [(0, "Cam")]

    @patch("dorso.v4l2_cameras._is_primary_node")
    @patch("dorso.v4l2_cameras._is_capture_device", return_value=True)
    @patch("dorso.v4l2_cameras._read_device_name", return_value="HP Camera")
    @patch("dorso.v4l2_cameras.os.path.exists", return_value=True)
    @patch("dorso.v4l2_cameras._SYS_VIDEO")
    def test_filters_secondary_nodes(self, mock_sys, mock_exists, mock_name, mock_capture, mock_primary):
        """Secondary nodes (index != 0) should be filtered out."""
        entry0 = MagicMock()
        entry0.name = "video0"
        entry1 = MagicMock()
        entry1.name = "video1"
        mock_sys.exists.return_value = True
        mock_sys.iterdir.return_value = [entry0, entry1]

        # video0 is primary, video1 is secondary
        mock_primary.side_effect = lambda n: n == "video0"

        result = list_cameras()
        assert result == [(0, "HP Camera")]
