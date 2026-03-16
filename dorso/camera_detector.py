"""Camera-based posture detector using MediaPipe Tasks API + OpenCV."""

from __future__ import annotations

import logging
import os
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Callable

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core import base_options as bo

from dorso.detector import PostureDetector
from dorso.models import CalibrationData, PostureReading

logger = logging.getLogger(__name__)

# Landmark indices (same as PoseLandmark enum)
_NOSE = 0
_LEFT_EAR = 7
_RIGHT_EAR = 8
_LEFT_SHOULDER = 11
_RIGHT_SHOULDER = 12

_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
_MODEL_FILENAME = "pose_landmarker_lite.task"


def _model_path() -> Path:
    """Return path to the pose landmarker model, downloading if needed."""
    xdg = os.environ.get("XDG_DATA_HOME")
    data_dir = Path(xdg) if xdg else Path.home() / ".local" / "share"
    model_dir = data_dir / "dorso" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_file = model_dir / _MODEL_FILENAME

    if not model_file.exists():
        logger.info("Downloading pose landmarker model...")
        urllib.request.urlretrieve(_MODEL_URL, model_file)
        logger.info("Model saved to %s", model_file)

    return model_file


class CameraDetector(PostureDetector):
    """Detects posture via webcam using MediaPipe PoseLandmarker."""

    def __init__(self, camera_id: int = 0, sensitivity: float = 0.03) -> None:
        super().__init__()
        self._camera_id = camera_id
        self._sensitivity = sensitivity
        self._calibration: CalibrationData | None = None
        self._capture: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._interval = 0.25
        self._smoothing_window: deque[float] = deque(maxlen=5)

    @property
    def calibration(self) -> CalibrationData | None:
        return self._calibration

    @calibration.setter
    def calibration(self, data: CalibrationData | None) -> None:
        self._calibration = data

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def is_available(self) -> bool:
        try:
            cap = cv2.VideoCapture(self._camera_id)
            ok = cap.isOpened()
            cap.release()
            return ok
        except Exception:
            return False

    def is_active(self) -> bool:
        return self._running

    def set_interval(self, interval: float) -> None:
        self._interval = interval

    def calibrate(self, on_complete: Callable[[CalibrationData | None], None]) -> None:
        thread = threading.Thread(
            target=self._calibrate_worker, args=(on_complete,), daemon=True
        )
        thread.start()

    def _create_landmarker(self) -> vision.PoseLandmarker:
        """Create a PoseLandmarker instance."""
        model = _model_path()
        options = vision.PoseLandmarkerOptions(
            base_options=bo.BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        return vision.PoseLandmarker.create_from_options(options)

    def _calibrate_worker(self, on_complete: Callable[[CalibrationData | None], None]) -> None:
        cap = cv2.VideoCapture(self._camera_id)
        if not cap.isOpened():
            logger.error("Cannot open camera %s for calibration", self._camera_id)
            on_complete(None)
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        try:
            landmarker = self._create_landmarker()
        except Exception as e:
            logger.error("Failed to create pose landmarker: %s", e)
            cap.release()
            on_complete(None)
            return

        nose_ys: list[float] = []
        face_widths: list[float] = []
        target_samples = 30

        try:
            for _ in range(target_samples * 3):
                if len(nose_ys) >= target_samples:
                    break

                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue

                nose_y, face_w = self._extract_landmarks(landmarker, frame)
                if nose_y is not None and face_w is not None:
                    nose_ys.append(nose_y)
                    face_widths.append(face_w)

                time.sleep(0.1)

            if len(nose_ys) < 10:
                logger.warning("Calibration failed: only %d samples", len(nose_ys))
                on_complete(None)
                return

            data = CalibrationData(
                nose_y=float(np.mean(nose_ys)),
                face_width=float(np.mean(face_widths)),
            )
            self._calibration = data
            logger.info(
                "Calibration done: nose_y=%.4f, face_width=%.4f (%d samples)",
                data.nose_y, data.face_width, len(nose_ys),
            )
            on_complete(data)

        finally:
            landmarker.close()
            cap.release()

    def _capture_loop(self) -> None:
        """Main detection loop running in a background thread."""
        self._capture = cv2.VideoCapture(self._camera_id)
        if not self._capture.isOpened():
            logger.error("Cannot open camera %s", self._camera_id)
            self._running = False
            return

        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        try:
            landmarker = self._create_landmarker()
        except Exception as e:
            logger.error("Failed to create pose landmarker: %s", e)
            self._running = False
            if self._capture:
                self._capture.release()
            return

        try:
            while self._running:
                ret, frame = self._capture.read()
                if not ret:
                    time.sleep(0.1)
                    continue

                reading = self._process_frame(landmarker, frame)
                if self.on_reading:
                    self.on_reading(reading)

                time.sleep(self._interval)
        finally:
            landmarker.close()
            if self._capture:
                self._capture.release()
                self._capture = None

    def _process_frame(self, landmarker: vision.PoseLandmarker, frame: np.ndarray) -> PostureReading:
        """Analyze a single frame and produce a PostureReading."""
        now = time.time()

        nose_y, face_width = self._extract_landmarks(landmarker, frame)

        if nose_y is None:
            self._smoothing_window.clear()
            return PostureReading.no_face(now)

        # Smooth nose_y
        self._smoothing_window.append(nose_y)
        smoothed_y = sum(self._smoothing_window) / len(self._smoothing_window)

        if self._calibration is None:
            return PostureReading(
                timestamp=now, is_slouching=False, severity=0.0, face_detected=True
            )

        # Nose Y increases when slouching (head drops)
        y_drop = smoothed_y - self._calibration.nose_y
        is_slouching = y_drop > self._sensitivity

        if is_slouching:
            max_drop = self._sensitivity * 5
            severity = min(1.0, max(0.0, (y_drop - self._sensitivity) / (max_drop - self._sensitivity)))

            # Forward head detection (face getting wider = closer to screen)
            if face_width is not None and self._calibration.face_width > 0:
                width_increase = (face_width - self._calibration.face_width) / self._calibration.face_width
                if width_increase > 0.05:
                    forward_severity = min(1.0, (width_increase - 0.05) / 0.10)
                    severity = min(1.0, max(severity, forward_severity))
        else:
            severity = 0.0

        return PostureReading(
            timestamp=now,
            is_slouching=is_slouching,
            severity=severity,
            face_detected=True,
        )

    @staticmethod
    def _extract_landmarks(
        landmarker: vision.PoseLandmarker, frame: np.ndarray
    ) -> tuple[float | None, float | None]:
        """Extract nose Y and face width from a frame.

        Returns (nose_y, face_width) normalized [0, 1], or (None, None).
        """
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        result = landmarker.detect(mp_image)

        if not result.pose_landmarks or len(result.pose_landmarks) == 0:
            return None, None

        landmarks = result.pose_landmarks[0]
        nose = landmarks[_NOSE]

        if nose.visibility is not None and nose.visibility < 0.5:
            return None, None

        nose_y = nose.y

        # Face width from ear-to-ear distance
        left_ear = landmarks[_LEFT_EAR]
        right_ear = landmarks[_RIGHT_EAR]
        le_vis = left_ear.visibility if left_ear.visibility is not None else 0.0
        re_vis = right_ear.visibility if right_ear.visibility is not None else 0.0

        if le_vis > 0.3 and re_vis > 0.3:
            face_width = abs(left_ear.x - right_ear.x)
        else:
            # Fallback: shoulder width as proxy
            left_sh = landmarks[_LEFT_SHOULDER]
            right_sh = landmarks[_RIGHT_SHOULDER]
            ls_vis = left_sh.visibility if left_sh.visibility is not None else 0.0
            rs_vis = right_sh.visibility if right_sh.visibility is not None else 0.0
            if ls_vis > 0.3 and rs_vis > 0.3:
                face_width = abs(left_sh.x - right_sh.x) * 0.4
            else:
                face_width = None

        return nose_y, face_width
