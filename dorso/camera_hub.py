"""Shared camera hub — single VideoCapture, frames distributed to subscribers."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class _Subscriber:
    callback: Callable[[np.ndarray], None]
    fps: float
    last_sent: float = 0.0


class CameraHub:
    """Owns the single VideoCapture and distributes frames by callback.

    - Opens camera on first subscribe, closes on last unsubscribe.
    - Each subscriber gets frames throttled to its requested fps.
    - Thread-safe subscribe/unsubscribe.
    """

    def __init__(self, dev_path: str) -> None:
        self._dev_path = dev_path
        self._lock = threading.Lock()
        self._subscribers: dict[str, _Subscriber] = {}
        self._capture: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    @property
    def dev_path(self) -> str:
        return self._dev_path

    def subscribe(
        self, name: str, callback: Callable[[np.ndarray], None], fps: float = 10.0
    ) -> None:
        """Register a frame consumer. Starts capture thread if first subscriber."""
        with self._lock:
            self._subscribers[name] = _Subscriber(callback=callback, fps=fps)
            logger.debug("Hub: +%s (fps=%.1f), %d subscribers", name, fps, len(self._subscribers))
        if not self._running:
            self._start_capture()

    def unsubscribe(self, name: str) -> None:
        """Remove a consumer. Stops capture thread if last subscriber."""
        with self._lock:
            self._subscribers.pop(name, None)
            remaining = len(self._subscribers)
            logger.debug("Hub: -%s, %d subscribers", name, remaining)
        if remaining == 0:
            self._stop_capture()

    def set_device(self, dev_path: str) -> None:
        """Switch camera device. Existing subscribers stay registered."""
        if dev_path == self._dev_path:
            return
        logger.info("Hub: switching %s → %s", self._dev_path, dev_path)
        was_running = self._running
        if was_running:
            self._stop_capture()
        self._dev_path = dev_path
        if was_running:
            self._start_capture()

    def is_available(self) -> bool:
        """Check if the camera device can be opened."""
        try:
            cap = cv2.VideoCapture(self._dev_path, cv2.CAP_V4L2)
            ok = cap.isOpened()
            cap.release()
            return ok
        except Exception:
            return False

    def shutdown(self) -> None:
        """Stop capture and release all resources."""
        self._stop_capture()
        with self._lock:
            self._subscribers.clear()

    # -- Internal --

    def _start_capture(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _stop_capture(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _capture_loop(self) -> None:
        cap = cv2.VideoCapture(self._dev_path, cv2.CAP_V4L2)
        if not cap.isOpened():
            logger.error("Hub: cannot open %s", self._dev_path)
            self._running = False
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        try:
            while self._running:
                # Compute target fps = max of all subscribers
                with self._lock:
                    if not self._subscribers:
                        break
                    max_fps = max(s.fps for s in self._subscribers.values())

                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue

                now = time.monotonic()

                # Dispatch to each subscriber (throttled)
                with self._lock:
                    subscribers = list(self._subscribers.items())

                for name, sub in subscribers:
                    interval = 1.0 / sub.fps if sub.fps > 0 else 1.0
                    if now - sub.last_sent >= interval * 0.9:  # 10% tolerance
                        sub.last_sent = now
                        try:
                            sub.callback(frame.copy())
                        except Exception:
                            logger.exception("Hub: error in subscriber %s", name)

                # Sleep to match target fps
                sleep_time = 1.0 / max_fps if max_fps > 0 else 0.1
                time.sleep(sleep_time)
        finally:
            cap.release()
            self._running = False
            logger.debug("Hub: capture loop ended")
