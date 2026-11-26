"""gettext wrapper (HANDOVER §2). English ships; the Language setting appears only once a 100 % catalogue exists."""
from __future__ import annotations

import gettext
import os

DOMAIN = "kluis"
LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locale")
_t = gettext.translation(DOMAIN, LOCALE_DIR, fallback=True)


def _(s: str) -> str:
    return _t.gettext(s)


def ngettext(s: str, p: str, n: int) -> str:
    return _t.ngettext(s, p, n)


def complete_languages() -> list[str]:
    """Languages with a full catalogue. Only English for 1.0, so the setting stays hidden."""
    return ["en"]
