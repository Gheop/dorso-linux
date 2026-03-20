"""Tests for the analytics module — DayStats and Analytics."""

from __future__ import annotations

import time
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from dorso.analytics import Analytics, DayStats


class TestDayStats:
    def test_compute_score_zero_monitoring(self):
        """No monitoring time should give a perfect score of 100."""
        ds = DayStats(date="2026-01-01", monitoring_seconds=0)
        ds.compute_score()
        assert ds.score == 100

    def test_compute_score_all_slouch(self):
        """100% slouch time should give score 0."""
        ds = DayStats(date="2026-01-01", monitoring_seconds=100, slouch_seconds=100)
        ds.compute_score()
        assert ds.score == 0

    def test_compute_score_half_slouch(self):
        """50% slouch time should give score ~50."""
        ds = DayStats(date="2026-01-01", monitoring_seconds=100, slouch_seconds=50)
        ds.compute_score()
        assert ds.score == 50

    def test_to_dict_from_dict_round_trip(self):
        """to_dict → from_dict should preserve all fields."""
        original = DayStats(
            date="2026-03-15",
            monitoring_seconds=3600.0,
            slouch_seconds=900.0,
            slouch_events=12,
            score=75,
        )
        restored = DayStats.from_dict(original.to_dict())
        assert restored.date == original.date
        assert restored.monitoring_seconds == pytest.approx(original.monitoring_seconds, abs=0.1)
        assert restored.slouch_seconds == pytest.approx(original.slouch_seconds, abs=0.1)
        assert restored.slouch_events == original.slouch_events
        assert restored.score == original.score


class TestAnalyticsMonitoring:
    def test_start_stop_accumulates_time(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        a = Analytics()

        t = time.time()
        with patch("dorso.analytics.time.time", return_value=t):
            a.start_monitoring()
        with patch("dorso.analytics.time.time", return_value=t + 10.0):
            a.stop_monitoring()

        assert a._today().monitoring_seconds == pytest.approx(10.0)

    def test_tick_accumulates_time(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        a = Analytics()

        t = time.time()
        with patch("dorso.analytics.time.time", return_value=t):
            a.start_monitoring()
        with patch("dorso.analytics.time.time", return_value=t + 5.0):
            a.tick()

        assert a._today().monitoring_seconds == pytest.approx(5.0)


class TestAnalyticsSlouch:
    def test_slouch_start_end_tracking(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        a = Analytics()

        t = time.time()
        with patch("dorso.analytics.time.time", return_value=t):
            a.start_monitoring()
            a.on_slouch_start()
        with patch("dorso.analytics.time.time", return_value=t + 3.0):
            a.on_slouch_end()

        today = a._today()
        assert today.slouch_events == 1
        assert today.slouch_seconds == pytest.approx(3.0)

    def test_slouch_start_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        a = Analytics()

        t = time.time()
        with patch("dorso.analytics.time.time", return_value=t):
            a.on_slouch_start()
            a.on_slouch_start()  # second call should be ignored

        assert a._today().slouch_events == 1


class TestAnalyticsToday:
    def test_today_creates_daystats_if_absent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        a = Analytics()
        assert a._days == {}

        today = a._today()
        assert today.date == date.today().isoformat()
        assert today.date in a._days

    def test_today_returns_existing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        a = Analytics()
        first = a._today()
        second = a._today()
        assert first is second


class TestAnalyticsLastNDays:
    def test_last_n_days_fills_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        a = Analytics()

        # Only populate today
        a._today().monitoring_seconds = 100.0

        days = a.last_n_days(7)
        assert len(days) == 7
        # Last entry is today
        assert days[-1].date == date.today().isoformat()
        assert days[-1].monitoring_seconds == 100.0
        # Earlier entries are empty defaults
        assert days[0].monitoring_seconds == 0.0
        assert days[0].score == 100


class TestAnalyticsPersistence:
    def test_save_load_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        a = Analytics()
        today = a._today()
        today.monitoring_seconds = 3600.0
        today.slouch_seconds = 600.0
        today.slouch_events = 5
        today.compute_score()
        a.save()

        b = Analytics()  # load() called in __init__
        loaded = b._today()
        assert loaded.monitoring_seconds == pytest.approx(3600.0, abs=0.1)
        assert loaded.slouch_seconds == pytest.approx(600.0, abs=0.1)
        assert loaded.slouch_events == 5

    def test_save_purges_old_entries(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        a = Analytics()

        # Add an entry from 100 days ago (should be purged)
        old_date = (date.today() - timedelta(days=100)).isoformat()
        a._days[old_date] = DayStats(date=old_date, monitoring_seconds=999)

        # Add today (should be kept)
        a._today().monitoring_seconds = 100.0
        a.save()

        b = Analytics()
        assert old_date not in b._days
        assert date.today().isoformat() in b._days
