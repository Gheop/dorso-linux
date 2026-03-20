"""Tests for landmark_overlay — draw_landmarks logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from dorso.landmark_overlay import (
    _FACE_CONNECTIONS,
    _NOSE,
    _SHOULDER_CONNECTION,
    draw_landmarks,
)


def _make_landmark(x, y, visibility=1.0):
    lm = MagicMock()
    lm.x = x
    lm.y = y
    lm.visibility = visibility
    return lm



class TestDrawLandmarksNoFace:
    def test_none_landmarks_draws_question_mark(self):
        """No landmarks → draw '?' indicator, return frame."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        with patch("dorso.landmark_overlay.cv2") as mock_cv2:
            result = draw_landmarks(frame, None)
        mock_cv2.putText.assert_called_once()
        assert result is frame


class TestDrawLandmarksWithFace:
    def test_draws_lines_and_circles(self):
        """Visible landmarks should produce line and circle calls."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        landmarks = [_make_landmark(0.5, 0.5) for _ in range(33)]

        with patch("dorso.landmark_overlay.cv2") as mock_cv2:
            result = draw_landmarks(frame, landmarks)

        # Face connections (4) + shoulder connection (1) = 5 lines
        assert mock_cv2.line.call_count == len(_FACE_CONNECTIONS) + len(_SHOULDER_CONNECTION)
        # 7 landmarks × 2 circles each (filled + outline) = 14
        assert mock_cv2.circle.call_count == 14
        assert result is frame

    def test_low_visibility_skips_drawing(self):
        """Landmarks with visibility < 0.3 should not be drawn."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        # All landmarks invisible
        landmarks = [_make_landmark(0.5, 0.5, visibility=0.1) for _ in range(33)]

        with patch("dorso.landmark_overlay.cv2") as mock_cv2:
            draw_landmarks(frame, landmarks)

        mock_cv2.line.assert_not_called()
        mock_cv2.circle.assert_not_called()

    def test_coordinate_scaling(self):
        """Landmark coords should be scaled to frame dimensions."""
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        landmarks = [_make_landmark(0.5, 0.5) for _ in range(33)]
        landmarks[_NOSE] = _make_landmark(0.25, 0.75, 1.0)

        with patch("dorso.landmark_overlay.cv2") as mock_cv2:
            draw_landmarks(frame, landmarks)

        # Find the nose circle call — nose is drawn first (index 0 in the loop)
        circle_calls = mock_cv2.circle.call_args_list
        # First circle call should be for nose: (0.25 * 200, 0.75 * 100) = (50, 75)
        nose_pt = circle_calls[0][0][1]  # second positional arg is the point
        assert nose_pt == (50, 75)
