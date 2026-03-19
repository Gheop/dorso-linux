"""Camera-based posture detector using MediaPipe Tasks API + OpenCV."""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from dorso.camera_hub import CameraHub
from dorso.detector import PostureDetector
from dorso.models import CalibrationData, PostureReading

logger = logging.getLogger(__name__)

from dorso.landmark_overlay import (
    _LEFT_EAR,
    _LEFT_SHOULDER,
    _NOSE,
    _RIGHT_EAR,
    _RIGHT_SHOULDER,
)

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
    """Detects posture via webcam using MediaPipe PoseLandmarker.

    Receives frames from a CameraHub instead of owning a VideoCapture.
    """

    def __init__(self, hub: CameraHub, sensitivity: float = 0.03) -> None:
        super().__init__()
        self._hub = hub
        self._sensitivity = sensitivity
        self._calibration: CalibrationData | None = None
        self._interval = 0.25
        self._running = False
        self._smoothing_window: deque[float] = deque(maxlen=5)
        self._landmarker = None
        self._landmarker_lock = threading.Lock()

    @property
    def calibration(self) -> CalibrationData | None:
        return self._calibration

    @calibration.setter
    def calibration(self, data: CalibrationData | None) -> None:
        self._calibration = data
        self._smoothing_window.clear()

    @property
    def sensitivity(self) -> float:
        return self._sensitivity

    @sensitivity.setter
    def sensitivity(self, value: float) -> None:
        self._sensitivity = value

    def start(self) -> None:
        if self._running:
            return
        self._ensure_landmarker()
        self._running = True
        fps = 1.0 / self._interval if self._interval > 0 else 4.0
        self._hub.subscribe("detector", self._on_frame, fps=fps)

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._hub.unsubscribe("detector")
        with self._landmarker_lock:
            if self._landmarker is not None:
                self._landmarker.close()
                self._landmarker = None

    def is_available(self) -> bool:
        return self._hub.is_available()

    def is_active(self) -> bool:
        return self._running

    def set_interval(self, interval: float) -> None:
        self._interval = interval
        if self._running:
            fps = 1.0 / interval if interval > 0 else 4.0
            self._hub.subscribe("detector", self._on_frame, fps=fps)

    def calibrate(self, on_complete: Callable[[CalibrationData | None], None]) -> None:
        thread = threading.Thread(
            target=self._calibrate_worker, args=(on_complete,), daemon=True
        )
        thread.start()

    def _ensure_landmarker(self) -> None:
        with self._landmarker_lock:
            if self._landmarker is None:
                try:
                    self._landmarker = self._create_landmarker()
                except Exception as e:
                    logger.error("Failed to create pose landmarker: %s", e)

    @staticmethod
    def _create_landmarker():
        """Create a PoseLandmarker instance (lazy-imports mediapipe)."""
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.core import base_options as bo

        model = _model_path()
        options = vision.PoseLandmarkerOptions(
            base_options=bo.BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        return vision.PoseLandmarker.create_from_options(options)

    def _on_frame(self, frame: np.ndarray) -> None:
        """Called by CameraHub with each frame."""
        if not self._running:
            return
        with self._landmarker_lock:
            if self._landmarker is None:
                return
            reading = self._process_frame(self._landmarker, frame)
        if self.on_reading:
            self.on_reading(reading)

    def _calibrate_worker(self, on_complete: Callable[[CalibrationData | None], None]) -> None:
        """Collect calibration samples via hub subscription."""
        try:
            landmarker = self._create_landmarker()
        except Exception as e:
            logger.error("Failed to create pose landmarker for calibration: %s", e)
            on_complete(None)
            return

        frame_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=5)

        def on_cal_frame(frame: np.ndarray) -> None:
            try:
                frame_queue.put_nowait(frame)
            except queue.Full:
                pass

        self._hub.subscribe("calibration", on_cal_frame, fps=10.0)

        nose_ys: list[float] = []
        face_widths: list[float] = []
        target_samples = 30

        try:
            for _ in range(target_samples * 3):
                if len(nose_ys) >= target_samples:
                    break

                try:
                    frame = frame_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                nose_y, face_w = self._extract_landmarks(landmarker, frame)
                if nose_y is not None and face_w is not None:
                    nose_ys.append(nose_y)
                    face_widths.append(face_w)

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
            self._hub.unsubscribe("calibration")

    def _process_frame(self, landmarker, frame: np.ndarray) -> PostureReading:
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
        landmarker, frame: np.ndarray
    ) -> tuple[float | None, float | None]:
        """Extract nose Y and face width from a frame.

        Returns (nose_y, face_width) normalized [0, 1], or (None, None).
        """
        import mediapipe as mp

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
