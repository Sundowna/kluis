"""Month scrubber ring mapping (HANDOVER §3.5, decisions D16). Pure functions, unit-tested.

ring_position(scroll, viewport, content, offsets) -> float dot index in [0, N-1]:
  * follows the month at the top edge of the viewport, interpolated inside the month, so a month
    whose heading sits at the top shows its own dot (F9 step 8) and the first months are reachable;
  * over the last viewport-height of scrolling it eases across the remaining dots, so the ring
    reaches the last dot exactly at the bottom (no jump at the end);
  * monotonic in `scroll`, never moves more than the content scrolled justifies.
"""
from __future__ import annotations

import bisect


def _smooth(t: float) -> float:
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return t * t * (3 - 2 * t)


def _base(y: float, offsets: list[float], content: float) -> float:
    n = len(offsets)
    i = max(0, bisect.bisect_right(offsets, y) - 1)
    start = offsets[i]
    end = offsets[i + 1] if i + 1 < n else content
    h = max(end - start, 1.0)
    return min(i + max(0.0, min(1.0, (y - start) / h)), n - 1)


def ring_position(scroll: float, viewport: float, content: float, offsets: list[float]) -> float:
    n = len(offsets)
    if n <= 1:
        return 0.0
    smax = max(content - viewport, 0.0)
    if smax <= 0:
        return 0.0
    s = max(0.0, min(scroll, smax))
    base = _base(s, offsets, content)
    end_base = _base(smax, offsets, content)
    span = min(viewport, smax)
    t = (s - (smax - span)) / span if span > 0 else 1.0
    return min(n - 1.0, base + _smooth(t) * ((n - 1) - end_base))


def scroll_for_dot(i: int, viewport: float, content: float, offsets: list[float]) -> float:
    """Scroll position that puts month i's heading at the top (clamped to the scroll range)."""
    smax = max(content - viewport, 0.0)
    return max(0.0, min(offsets[i] if 0 <= i < len(offsets) else 0.0, smax))


def nearest_dot(pos: float) -> int:
    return int(pos + 0.5)
