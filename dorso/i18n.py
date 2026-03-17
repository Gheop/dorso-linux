"""Internationalization — gettext setup with automatic locale detection."""

import gettext
import os
from pathlib import Path

_localedir = Path(__file__).parent.parent / "locales"

# Build language list from environment (LANGUAGE, LC_ALL, LC_MESSAGES, LANG)
_languages = None
for _var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
    _val = os.environ.get(_var)
    if _val:
        _languages = [_val.split(".")[0]]  # strip .UTF-8
        break

_translation = gettext.translation("dorso", _localedir, languages=_languages, fallback=True)
_ = _translation.gettext
