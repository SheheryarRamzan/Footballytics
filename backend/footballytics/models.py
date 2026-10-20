"""Transparent football models (expected goals and expected threat).

Both models are deliberately simple and explainable: every output can be broken down
into named factors, which the agents use when they explain *why* a moment matters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .pitch import PITCH_LENGTH, PITCH_WIDTH, distance_to_goal, goal_opening_angle

# Logistic xG coefficients, fitted to public reference points:
# 6 m central ~0.55, penalty-spot open play ~0.28, 18 m ~0.09, 25 m ~0.03.
_XG_B0, _XG_DIST, _XG_ANGLE = 0.588, -0.1744, 0.601
PENALTY_XG = 0.76


@dataclass(frozen=True)
class XGBreakdown:
    xg: float
    distance_m: float
    angle_deg: float
    base: float
    header_factor: float
    pressure_factor: float
    situation: str

    def factors(self) -> dict[str, float | str]:
        return {
            "distance_m": round(self.distance_m, 1),
            "angle_deg": round(self.angle_deg, 1),
            "base_xg_from_location": round(self.base, 3),
            "header_factor": self.header_factor,
            "pressure_factor": round(self.pressure_factor, 2),
            "situation": self.situation,
        }


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def expected_goals(
    x: float,
    y: float,
    *,
    header: bool = False,
    pressure: float = 0.0,
    situation: str = "open_play",
) -> XGBreakdown:
    """xG for a shot at (x, y) in team frame. ``pressure`` is 0..1 (defender proximity)."""
    dist = distance_to_goal(x, y)
    angle = goal_opening_angle(x, y)
    if situation == "penalty":
        return XGBreakdown(PENALTY_XG, 11.0, math.degrees(angle), PENALTY_XG, 1.0, 1.0, situation)
    base = _sigmoid(_XG_B0 + _XG_DIST * dist + _XG_ANGLE * angle)
    header_factor = 0.55 if header else 1.0
    pressure_factor = 1.0 - 0.3 * max(0.0, min(1.0, pressure))
    situation_factor = 1.15 if situation == "direct_free_kick" and dist < 25 else 1.0
    xg = min(0.97, base * header_factor * pressure_factor * situation_factor)
    return XGBreakdown(xg, dist, math.degrees(angle), base, header_factor, pressure_factor, situation)


def expected_threat(x: float, y: float) -> float:
    """Smooth expected-threat surface (team frame): chance this location leads to a goal soon.

    Shape follows the well-known xT grid: near zero in the defensive half, rising sharply
    in the zone between the penalty spot and the six-yard box, and higher centrally.
    """
    x = max(0.0, min(PITCH_LENGTH, x))
    y = max(0.0, min(PITCH_WIDTH, y))
    progress = x / PITCH_LENGTH
    centrality = 1.0 - abs(y - PITCH_WIDTH / 2) / (PITCH_WIDTH / 2)
    build_up = 0.006 + 0.03 * progress**3
    dist = distance_to_goal(x, y)
    danger = 0.30 * math.exp(-((dist / 13.0) ** 2)) * (0.55 + 0.45 * centrality)
    return build_up + danger
