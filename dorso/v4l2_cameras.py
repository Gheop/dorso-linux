"""V4L2 camera enumeration — list capture devices with human-readable names."""

from __future__ import annotations

import fcntl
import logging
import os
import struct
from pathlib import Path

logger = logging.getLogger(__name__)

# V4L2 ioctl constants
_VIDIOC_QUERYCAP = 0x80685600
_V4L2_CAP_VIDEO_CAPTURE = 0x00000001

_SYS_VIDEO = Path("/sys/class/video4linux")

# Infrared cameras can't produce useful RGB video for posture detection
_IR_KEYWORDS = ("ir camera", "infrared")


def _is_capture_device(dev_path: str) -> bool:
    """Check if a /dev/videoN device supports V4L2 video capture."""
    try:
        fd = os.open(dev_path, os.O_RDWR | os.O_NONBLOCK)
        try:
            buf = bytearray(104)  # sizeof(struct v4l2_capability)
            fcntl.ioctl(fd, _VIDIOC_QUERYCAP, buf)
            # device_caps is at offset 84 (uint32_t)
            caps = struct.unpack_from("<I", buf, 84)[0]
            return bool(caps & _V4L2_CAP_VIDEO_CAPTURE)
        finally:
            os.close(fd)
    except OSError:
        return False


def _read_device_name(video_name: str) -> str:
    """Read /sys/class/video4linux/videoN/name, cleaned up.

    V4L2 names often duplicate vendor/product like
    "HP 5MP Camera: HP 5MP Camera" → return just "HP 5MP Camera".
    """
    try:
        raw = (_SYS_VIDEO / video_name / "name").read_text().strip()
    except OSError:
        return video_name

    # Clean "Vendor: Product" where product starts with vendor prefix
    if ": " in raw:
        vendor, product = raw.split(": ", 1)
        if product.startswith(vendor) or vendor.startswith(product):
            return product if len(product) >= len(vendor) else vendor
    return raw


def _is_primary_node(video_name: str) -> bool:
    """Check if this is the primary (index 0) node for its device.

    Each physical camera creates multiple /dev/videoN nodes (capture,
    metadata, etc.). Only the primary node (index 0) is the actual
    capture interface.
    """
    try:
        idx = (_SYS_VIDEO / video_name / "index").read_text().strip()
        return idx == "0"
    except OSError:
        # If index file doesn't exist, accept the device
        return True


def list_cameras() -> list[tuple[int, str]]:
    """List available V4L2 capture devices.

    Returns a sorted list of (device_index, display_name) tuples.
    Only returns the primary node per physical camera.
    Example: [(0, "Integrated Camera"), (4, "USB Webcam")]
    """
    if not _SYS_VIDEO.exists():
        return []

    cameras: list[tuple[int, str]] = []

    for entry in sorted(_SYS_VIDEO.iterdir(), key=lambda e: e.name):
        name = entry.name
        if not name.startswith("video"):
            continue
        try:
            index = int(name[len("video"):])
        except ValueError:
            continue

        dev_path = f"/dev/{name}"
        if not os.path.exists(dev_path):
            continue

        if not _is_primary_node(name):
            continue

        if not _is_capture_device(dev_path):
            continue

        display_name = _read_device_name(name)

        # Skip infrared cameras
        if any(kw in display_name.lower() for kw in _IR_KEYWORDS):
            continue

        cameras.append((index, display_name))

    return cameras
