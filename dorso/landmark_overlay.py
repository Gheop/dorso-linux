"""Draw pose landmarks on camera frames for visual feedback."""

from __future__ import annotations

import cv2
import numpy as np

# Landmark indices (same as camera_detector.py)
_NOSE = 0
_LEFT_EYE = 2
_RIGHT_EYE = 5
_LEFT_EAR = 7
_RIGHT_EAR = 8
_LEFT_SHOULDER = 11
_RIGHT_SHOULDER = 12

# Face contour connections (landmark pairs to draw lines between)
_FACE_CONNECTIONS = [
    (_LEFT_EAR, _LEFT_EYE),
    (_LEFT_EYE, _NOSE),
    (_NOSE, _RIGHT_EYE),
    (_RIGHT_EYE, _RIGHT_EAR),
]

_SHOULDER_CONNECTION = [
    (_LEFT_SHOULDER, _RIGHT_SHOULDER),
]

# Colors (BGR)
_COLOR_FACE = (80, 220, 180)  # teal
_COLOR_NOSE = (80, 180, 255)  # orange-ish
_COLOR_SHOULDER = (180, 180, 80)  # blue-teal
_COLOR_NO_FACE = (80, 80, 220)  # red-ish


def draw_landmarks(frame: np.ndarray, landmarks: list | None) -> np.ndarray:
    """Draw pose landmarks on a BGR frame. Returns the modified frame.

    Args:
        frame: BGR image (OpenCV format)
        landmarks: MediaPipe pose_landmarks[0] list, or None if no pose detected
    """
    h, w = frame.shape[:2]

    if landmarks is None:
        # No face detected — draw a subtle "no face" indicator
        cv2.putText(
            frame, "?", (w // 2 - 15, h // 2 + 15),
            cv2.FONT_HERSHEY_SIMPLEX, 1.5, _COLOR_NO_FACE, 3, cv2.LINE_AA,
        )
        return frame

    def _pt(idx: int) -> tuple[int, int] | None:
        lm = landmarks[idx]
        vis = lm.visibility if lm.visibility is not None else 0.0
        if vis < 0.3:
            return None
        return int(lm.x * w), int(lm.y * h)

    # Draw face contour lines
    for i, j in _FACE_CONNECTIONS:
        p1, p2 = _pt(i), _pt(j)
        if p1 and p2:
            cv2.line(frame, p1, p2, _COLOR_FACE, 2, cv2.LINE_AA)

    # Draw shoulder line
    for i, j in _SHOULDER_CONNECTION:
        p1, p2 = _pt(i), _pt(j)
        if p1 and p2:
            cv2.line(frame, p1, p2, _COLOR_SHOULDER, 2, cv2.LINE_AA)

    # Draw landmark dots
    for idx, color, radius in [
        (_NOSE, _COLOR_NOSE, 6),
        (_LEFT_EYE, _COLOR_FACE, 4),
        (_RIGHT_EYE, _COLOR_FACE, 4),
        (_LEFT_EAR, _COLOR_FACE, 4),
        (_RIGHT_EAR, _COLOR_FACE, 4),
        (_LEFT_SHOULDER, _COLOR_SHOULDER, 5),
        (_RIGHT_SHOULDER, _COLOR_SHOULDER, 5),
    ]:
        pt = _pt(idx)
        if pt:
            cv2.circle(frame, pt, radius, color, -1, cv2.LINE_AA)
            cv2.circle(frame, pt, radius, (255, 255, 255), 1, cv2.LINE_AA)

    return frame


def detect_and_draw(landmarker, frame: np.ndarray) -> np.ndarray:
    """Run pose detection and draw landmarks. Returns modified BGR frame.

    Args:
        landmarker: MediaPipe PoseLandmarker instance
        frame: BGR image
    """
    import mediapipe as mp

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = landmarker.detect(mp_image)

    landmarks = None
    if result.pose_landmarks and len(result.pose_landmarks) > 0:
        landmarks = result.pose_landmarks[0]

    return draw_landmarks(frame, landmarks)
