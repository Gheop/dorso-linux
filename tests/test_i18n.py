"""Tests for internationalization."""

import os
import subprocess
import sys


def test_english_fallback():
    """Unknown locale should fall back to English."""
    result = subprocess.run(
        [sys.executable, "-c", "from dorso.i18n import _; print(_('Calibrate'))"],
        capture_output=True, text=True,
        env={**os.environ, "LANG": "xx_XX", "LC_ALL": "xx_XX", "LANGUAGE": "xx"},
    )
    assert result.stdout.strip() == "Calibrate"


def test_french():
    """French locale should return French strings."""
    result = subprocess.run(
        [sys.executable, "-c", "from dorso.i18n import _; print(_('Calibrate'))"],
        capture_output=True, text=True,
        env={**os.environ, "LANG": "fr_FR.UTF-8", "LC_ALL": "fr_FR.UTF-8", "LANGUAGE": "fr"},
    )
    assert result.stdout.strip() == "Calibrer"


def test_all_po_files_compile():
    """All .po files should compile without errors."""
    from pathlib import Path
    locales_dir = Path(__file__).parent.parent / "locales"
    for po in locales_dir.glob("*/LC_MESSAGES/dorso.po"):
        result = subprocess.run(
            ["msgfmt", "--check", str(po), "-o", "/dev/null"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"{po} failed: {result.stderr}"
