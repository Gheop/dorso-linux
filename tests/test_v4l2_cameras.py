"""Tests for V4L2 camera enumeration (mocked filesystem + ioctl)."""

from __future__ import annotations

import struct
from unittest.mock import MagicMock, patch

from dorso.v4l2_cameras import (
    _V4L2_CAP_VIDEO_CAPTURE,
    _is_capture_device,
    _is_primary_node,
    _read_device_name,
    list_cameras,
)

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

    @_PRIMARY
    @patch("dorso.v4l2_cameras._is_capture_device", return_value=True)
    @patch("dorso.v4l2_cameras._read_device_name", return_value="IR Camera")
    @patch("dorso.v4l2_cameras.os.path.exists", return_value=True)
    @patch("dorso.v4l2_cameras._SYS_VIDEO")
    def test_filters_infrared_cameras(self, mock_sys, mock_exists, mock_name, mock_capture, mock_primary):
        """Infrared cameras should be filtered out."""
        entry = MagicMock()
        entry.name = "video0"
        mock_sys.exists.return_value = True
        mock_sys.iterdir.return_value = [entry]

        result = list_cameras()
        assert result == []


class TestIsCaptureDevice:
    @patch("dorso.v4l2_cameras.os.close")
    @patch("dorso.v4l2_cameras.fcntl.ioctl")
    @patch("dorso.v4l2_cameras.os.open", return_value=3)
    def test_capture_device_returns_true(self, mock_open, mock_ioctl, mock_close):
        """Device with V4L2_CAP_VIDEO_CAPTURE should return True."""
        def fill_buf(fd, cmd, buf):
            # Set device_caps at offset 84 to include VIDEO_CAPTURE
            struct.pack_into("<I", buf, 84, _V4L2_CAP_VIDEO_CAPTURE)
        mock_ioctl.side_effect = fill_buf
        assert _is_capture_device("/dev/video0") is True
        mock_close.assert_called_once_with(3)

    @patch("dorso.v4l2_cameras.os.close")
    @patch("dorso.v4l2_cameras.fcntl.ioctl")
    @patch("dorso.v4l2_cameras.os.open", return_value=3)
    def test_non_capture_device_returns_false(self, mock_open, mock_ioctl, mock_close):
        """Device without VIDEO_CAPTURE capability should return False."""
        def fill_buf(fd, cmd, buf):
            struct.pack_into("<I", buf, 84, 0)  # No capture cap
        mock_ioctl.side_effect = fill_buf
        assert _is_capture_device("/dev/video0") is False

    @patch("dorso.v4l2_cameras.os.open", side_effect=OSError("no device"))
    def test_os_error_returns_false(self, mock_open):
        """OSError when opening device should return False."""
        assert _is_capture_device("/dev/video99") is False


class TestReadDeviceName:
    @patch("dorso.v4l2_cameras._SYS_VIDEO")
    def test_deduplicates_vendor_product(self, mock_sys):
        """'HP 5MP Camera: HP 5MP Camera' should become 'HP 5MP Camera'."""
        mock_path = MagicMock()
        mock_path.read_text.return_value = "HP 5MP Camera: HP 5MP Camera\n"
        (mock_sys / "video0" / "name").__truediv__ = lambda *a: mock_path
        mock_sys.__truediv__ = lambda self, k: MagicMock(__truediv__=lambda self2, k2: mock_path)

        # Direct test with patched Path
        with patch("dorso.v4l2_cameras._SYS_VIDEO", mock_sys):
            result = _read_device_name("video0")
        assert result == "HP 5MP Camera"

    @patch("dorso.v4l2_cameras._SYS_VIDEO")
    def test_plain_name_unchanged(self, mock_sys):
        """Simple name without colon stays unchanged."""
        mock_path = MagicMock()
        mock_path.read_text.return_value = "Integrated Camera\n"
        mock_sys.__truediv__ = lambda self, k: MagicMock(__truediv__=lambda self2, k2: mock_path)

        result = _read_device_name("video0")
        assert result == "Integrated Camera"

    @patch("dorso.v4l2_cameras._SYS_VIDEO")
    def test_oserror_returns_video_name(self, mock_sys):
        """OSError reading name file should return the video name as fallback."""
        mock_path = MagicMock()
        mock_path.read_text.side_effect = OSError("no file")
        mock_sys.__truediv__ = lambda self, k: MagicMock(__truediv__=lambda self2, k2: mock_path)

        result = _read_device_name("video0")
        assert result == "video0"


class TestIsPrimaryNode:
    @patch("dorso.v4l2_cameras._SYS_VIDEO")
    def test_index_zero_is_primary(self, mock_sys):
        """Index file containing '0' → primary."""
        mock_path = MagicMock()
        mock_path.read_text.return_value = "0\n"
        mock_sys.__truediv__ = lambda self, k: MagicMock(__truediv__=lambda self2, k2: mock_path)

        assert _is_primary_node("video0") is True

    @patch("dorso.v4l2_cameras._SYS_VIDEO")
    def test_index_nonzero_is_not_primary(self, mock_sys):
        """Index file containing '1' → not primary."""
        mock_path = MagicMock()
        mock_path.read_text.return_value = "1\n"
        mock_sys.__truediv__ = lambda self, k: MagicMock(__truediv__=lambda self2, k2: mock_path)

        assert _is_primary_node("video1") is False

    @patch("dorso.v4l2_cameras._SYS_VIDEO")
    def test_oserror_returns_true(self, mock_sys):
        """Missing index file → accept device (return True)."""
        mock_path = MagicMock()
        mock_path.read_text.side_effect = OSError("no file")
        mock_sys.__truediv__ = lambda self, k: MagicMock(__truediv__=lambda self2, k2: mock_path)

        assert _is_primary_node("video0") is True
