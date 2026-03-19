"""Posture analytics — tracks slouch events and computes daily scores."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    d = base / "dorso"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _analytics_path() -> Path:
    return _data_dir() / "analytics.json"


@dataclass
class DayStats:
    """Statistics for a single day."""

    date: str  # ISO format YYYY-MM-DD
    monitoring_seconds: float = 0.0
    slouch_seconds: float = 0.0
    slouch_events: int = 0
    score: int = 100  # 0-100, computed

    def compute_score(self) -> None:
        """Score = % of monitoring time with good posture."""
        if self.monitoring_seconds <= 0:
            self.score = 100
            return
        good_ratio = max(0, 1.0 - self.slouch_seconds / self.monitoring_seconds)
        self.score = int(round(good_ratio * 100))

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "monitoring_seconds": round(self.monitoring_seconds, 1),
            "slouch_seconds": round(self.slouch_seconds, 1),
            "slouch_events": self.slouch_events,
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DayStats:
        return cls(
            date=d["date"],
            monitoring_seconds=d.get("monitoring_seconds", 0),
            slouch_seconds=d.get("slouch_seconds", 0),
            slouch_events=d.get("slouch_events", 0),
            score=d.get("score", 100),
        )


class Analytics:
    """Tracks posture data and persists to JSON."""

    def __init__(self) -> None:
        self._days: dict[str, DayStats] = {}
        self._monitoring_start: float | None = None
        self._slouch_start: float | None = None
        self.load()

    def load(self) -> None:
        path = _analytics_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            for d in data.get("days", []):
                stats = DayStats.from_dict(d)
                self._days[stats.date] = stats
        except Exception as e:
            logger.warning("Failed to load analytics: %s", e)

    def save(self) -> None:
        # Keep last 90 days
        cutoff = (date.today() - timedelta(days=90)).isoformat()
        self._days = {k: v for k, v in self._days.items() if k >= cutoff}

        data = {
            "days": [s.to_dict() for s in sorted(self._days.values(), key=lambda s: s.date)]
        }
        try:
            _analytics_path().write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning("Failed to save analytics: %s", e)

    def _today(self) -> DayStats:
        key = date.today().isoformat()
        if key not in self._days:
            self._days[key] = DayStats(date=key)
        return self._days[key]

    def start_monitoring(self) -> None:
        self._monitoring_start = time.time()

    def stop_monitoring(self) -> None:
        if self._monitoring_start:
            elapsed = time.time() - self._monitoring_start
            self._today().monitoring_seconds += elapsed
            self._monitoring_start = None
        if self._slouch_start:
            self._end_slouch()
        self._today().compute_score()
        self.save()

    def on_slouch_start(self) -> None:
        if self._slouch_start is None:
            self._slouch_start = time.time()
            self._today().slouch_events += 1

    def on_slouch_end(self) -> None:
        self._end_slouch()
        self._today().compute_score()
        self.save()

    def _end_slouch(self) -> None:
        if self._slouch_start:
            elapsed = time.time() - self._slouch_start
            self._today().slouch_seconds += elapsed
            self._slouch_start = None

    def tick(self) -> None:
        """Called periodically to update monitoring time."""
        if self._monitoring_start:
            now = time.time()
            elapsed = now - self._monitoring_start
            self._monitoring_start = now
            self._today().monitoring_seconds += elapsed

    @property
    def today(self) -> DayStats:
        self._today().compute_score()
        return self._today()

    def last_n_days(self, n: int = 7) -> list[DayStats]:
        """Return stats for the last n days (including today)."""
        result = []
        for i in range(n - 1, -1, -1):
            d = (date.today() - timedelta(days=i)).isoformat()
            if d in self._days:
                s = self._days[d]
                s.compute_score()
                result.append(s)
            else:
                result.append(DayStats(date=d))
        return result
