"""Deterministic narrative auditor: every number in generated text must be traceable to evidence.

LLMs are good at prose and bad at numbers. Rather than trusting a second LLM to "check" the
first, we extract every number from the text and require it to match a citable value in the evidence
(facts, verified claims, assessments) at the precision it was written, allowing common renderings
(0.31 vs 31%, 108.4 vs 108). Coordinates and identifiers are not citable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_NUM = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)(\s?%)?")


def numbers_in(text: str) -> list[tuple[float, bool, str]]:
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(1).replace(",", ".")
        try:
            out.append((float(raw), bool(m.group(2)), m.group(0).strip()))
        except ValueError:
            continue
    return out


# Keys whose numbers are not citable facts (pitch coordinates, identifiers, clocks): excluding them keeps
# the evidence pool tight, so an invented statistic cannot "match" a coordinate by coincidence.
NON_CITABLE = {"x", "y", "end_x", "end_y", "start", "end", "event_id", "moment_id", "match_id", "player_id",
               "team_id", "receiver_id", "assist_id", "shooter_id", "id", "seq", "t", "clock",
               "attack_dir", "home_attack_dir", "series_value"}


def collect_numbers(obj, acc: set[float] | None = None) -> set[float]:
    """Citable numeric facts in a nested structure: numeric leaves and numbers inside prose strings,
    skipping coordinates, identifiers and clocks."""
    acc = acc if acc is not None else set()
    if isinstance(obj, bool):
        return acc
    if isinstance(obj, int | float):
        acc.add(float(obj))
    elif isinstance(obj, str):
        if " " in obj:  # prose ("won the ball 16 m from goal"), not identifiers like "md11-FCR-KGA-m00123"
            for v, _, _ in numbers_in(obj):
                acc.add(v)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k not in NON_CITABLE:
                collect_numbers(v, acc)
    elif isinstance(obj, list | tuple | set):
        for v in obj:
            collect_numbers(v, acc)
    return acc


def _decimals(raw: str) -> int:
    digits = raw.rstrip("%").strip().replace(",", ".")
    return len(digits.split(".", 1)[1]) if "." in digits else 0


def _matches(value: float, is_pct: bool, allowed: Iterable[float], decimals: int = 0) -> bool:
    """A number written in prose matches evidence if it is that evidence rounded (or, for whole numbers,
    truncated) to the precision written. Percentages may render 0-1 ratios (0.62 -> 62%)."""
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    for a in allowed:
        candidates = [a * 100, a] if (is_pct and 0 <= a <= 1) else [a]
        for c in candidates:
            if abs(value - c) <= tol:
                return True
            if decimals == 0 and value == int(c) and c >= 0:  # truncation: 45.9 written as "45"
                return True
    return False


def unsupported_numbers(texts: Iterable[str], evidence: object, always_ok: Iterable[float] = ()) -> list[str]:
    """Numbers in ``texts`` that cannot be found in ``evidence``. Small counts (0-11) are allowed
    because they are usually ordinal/structural ("two defenders", "the 2nd goal")."""
    allowed = collect_numbers(evidence) | set(always_ok)
    bad = []
    for text in texts:
        for value, is_pct, raw in numbers_in(text):
            if value.is_integer() and 0 <= value <= 11 and not is_pct:
                continue
            if not _matches(value, is_pct, allowed, _decimals(raw)):
                bad.append(raw)
    return sorted(set(bad))
