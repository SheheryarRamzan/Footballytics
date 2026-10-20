"""Taste Learner: adapts what a fan sees from implicit signals, and explains what it learned.

Signals: skip (dismissed a card or cut back early), replay, like, dwell (watched a cut to the end),
ask (asked the pundit about it). Each nudges the weight of that moment kind multiplicatively, so a
few consistent signals move the needle and nothing collapses to zero.
"""

from __future__ import annotations

import time

from .profiles import MODE_WEIGHTS, FanProfile

FACTORS = {"skip": 0.8, "replay": 1.18, "like": 1.15, "dwell": 1.04, "ask": 1.1}
FLOOR, CEILING = 0.1, 2.0

KIND_LABELS = {
    "goal": "goals", "wonder_strike": "wonder goals", "big_chance": "big chances", "great_save": "big saves",
    "momentum_swing": "momentum swings", "control_shift": "control-vs-chaos shifts", "pressing_shift": "pressing changes",
    "tempo_shift": "tempo changes", "line_breaking_pass": "line-breaking passes", "sprint_tag": "sprint speed tags",
    "shot_speed": "shot-speed tags", "high_turnover": "high turnovers", "milestone": "milestones",
    "yellow_card": "yellow cards", "substitution": "substitutions", "penalty_awarded": "penalties",
}


def record(fan: FanProfile, signal: str, kind: str, moment_id: str | None = None) -> dict:
    """Apply one signal; returns the change so the UI can say "Got it: fewer momentum updates"."""
    factor = FACTORS.get(signal)
    if factor is None or not kind:
        return {"changed": False}
    before = fan.weights.get(kind, 0.5)
    after = round(min(CEILING, max(FLOOR, before * factor)), 3)
    fan.weights[kind] = after
    fan.signals.append({"signal": signal, "kind": kind, "moment_id": moment_id, "at": time.time()})
    fan.signals = fan.signals[-200:]
    return {"changed": after != before, "kind": kind, "before": before, "after": after,
            "message": message(kind, before, after)}


def message(kind: str, before: float, after: float) -> str:
    label = KIND_LABELS.get(kind, kind.replace("_", " "))
    if after < before:
        return f"Got it: fewer {label}."
    if after > before:
        return f"Noted: more {label}."
    return ""


def explain(fan: FanProfile) -> dict:
    """What the learner has learned, relative to the mode's defaults (shown in 'Why am I seeing this?')."""
    base = MODE_WEIGHTS.get(fan.mode, MODE_WEIGHTS["fan"])
    more, fewer = [], []
    for kind, w in fan.weights.items():
        b = base.get(kind, w)
        if w > b * 1.15:
            more.append(KIND_LABELS.get(kind, kind))
        elif w < b * 0.85:
            fewer.append(KIND_LABELS.get(kind, kind))
    parts = []
    if more:
        parts.append("showing you more " + ", ".join(more))
    if fewer:
        parts.append("fewer " + ", ".join(fewer))
    summary = ("Based on what you skip and replay, I'm " + " and ".join(parts) + ".") if parts else \
        "Still learning your taste: skip or replay cards and I'll adapt."
    return {"summary": summary, "more": more, "fewer": fewer, "signals": len(fan.signals), "weights": fan.weights}
