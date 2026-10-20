"""Deterministic narrative auditor: every number in generated text must be traceable to evidence.

LLMs are good at prose and bad at numbers. Rather than trusting a second LLM to "check" the
first, we extract every number from the text and require it to match a value in the evidence
(facts, verified claims, assessments) within a small tolerance, allowing common renderings
(0.31 vs 31%, 108.4 vs 108).
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


def collect_numbers(obj, acc: set[float] | None = None) -> set[float]:
    """All numeric leaves of a nested structure (dict/list), plus numbers embedded in strings."""
    acc = acc if acc is not None else set()
    if isinstance(obj, bool):
        return acc
    if isinstance(obj, int | float):
        acc.add(float(obj))
    elif isinstance(obj, str):
        for v, _, _ in numbers_in(obj):
            acc.add(v)
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_numbers(v, acc)
    elif isinstance(obj, list | tuple | set):
        for v in obj:
            collect_numbers(v, acc)
    return acc


def _matches(value: float, is_pct: bool, allowed: Iterable[float]) -> bool:
    for a in allowed:
        candidates = [a]
        if 0 <= a <= 1:
            candidates.append(a * 100)  # 0.31 written as 31%
        if is_pct and a > 1:
            candidates.append(a)
        for c in candidates:
            tol = max(0.011, abs(c) * 0.03) if c < 2 else max(0.6, abs(c) * 0.03)
            if abs(value - c) <= tol:
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
            if not _matches(value, is_pct, allowed):
                bad.append(raw)
    return sorted(set(bad))
