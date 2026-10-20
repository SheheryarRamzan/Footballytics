"""Tracking-aware football metrics. Every metric returns its explanatory factors.

All functions take *team-frame* coordinates (attacking towards x = 105) unless noted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..models import expected_goals, expected_threat
from ..pitch import PITCH_LENGTH, PITCH_WIDTH, point_segment_distance

SPRINT_KMH = 25.2  # common provider threshold for a sprint
TAG_SPEED_KMH = 30.5  # on-screen "speed tag" threshold
REACTION_S = 0.7
MAX_RUN_MPS = 7.8


def _sig(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


@dataclass
class PassAssessment:
    completion_prob: float
    difficulty: float  # 1 (routine) .. 10 (exceptional)
    length_m: float
    lane_clearance_m: float
    receiver_space_m: float
    passer_pressure_m: float
    defenders_bypassed: int
    lofted: bool
    xt_added: float
    accuracy: float | None = None  # 0..100, how well the ball met the receiver's run
    factors: dict = field(default_factory=dict)


def assess_pass(start: np.ndarray, end: np.ndarray, opponents: np.ndarray, lofted: bool,
                receiver_at_arrival: np.ndarray | None = None) -> PassAssessment:
    """Expected completion + difficulty for a pass from ``start`` to ``end`` given opponent positions.

    The completion model is an independent, interpretable logistic model (not the
    simulator's internal one), so the stats engine genuinely *measures* passes.
    """
    length = float(np.linalg.norm(end - start))
    if len(opponents):
        lane, tpar = point_segment_distance(opponents, start, end)
        lane = np.where(tpar > 0.08, lane, 99.0)
        lane_clear = float(lane.min())
        recv_space = float(np.min(np.linalg.norm(opponents - end, axis=1)))
        passer_press = float(np.min(np.linalg.norm(opponents - start, axis=1)))
        lo, hi = sorted((start[0], end[0]))
        bypassed = int(np.sum((opponents[:, 0] > lo) & (opponents[:, 0] < hi))) if end[0] > start[0] else 0
    else:
        lane_clear = recv_space = passer_press = 99.0
        bypassed = 0
    z = (3.6 - 0.045 * length - 2.0 * math.exp(-lane_clear / 1.6) - 1.1 * math.exp(-recv_space / 2.4)
         - 0.9 * math.exp(-passer_press / 2.0) - 0.18 * bypassed - (0.35 if lofted else 0.0)
         - (0.6 if end[0] > 70 else 0.0))
    p = _sig(z)
    difficulty = round(1 + 9 * (1 - p) ** 0.8, 1)
    xt_added = expected_threat(end[0], end[1]) - expected_threat(start[0], start[1])
    accuracy = None
    if receiver_at_arrival is not None:
        miss = float(np.linalg.norm(receiver_at_arrival - end))
        accuracy = round(max(0.0, 100.0 - 18.0 * max(0.0, miss - 0.6)), 0)
    factors = {
        "length_m": round(length, 1),
        "lane_clearance_m": round(lane_clear, 1),
        "receiver_space_m": round(recv_space, 1),
        "passer_pressure_m": round(passer_press, 1),
        "defenders_bypassed": bypassed,
        "lofted": lofted,
        "into_final_third": bool(end[0] > 70),
    }
    return PassAssessment(p, difficulty, length, lane_clear, recv_space, passer_press, bypassed, lofted,
                          xt_added, accuracy, factors)


def shot_xg(x: float, y: float, opponents: np.ndarray | None, header: bool, situation: str) -> tuple[float, dict]:
    """xG with pressure measured from tracking (nearest defender distance) plus blockers in the lane."""
    pressure = 0.0
    blockers = 0
    nearest = None
    if opponents is not None and len(opponents):
        d = np.linalg.norm(opponents - np.array([x, y]), axis=1)
        nearest = float(d.min())
        pressure = max(0.0, min(1.0, (3.5 - nearest) / 2.5))
        lane, tpar = point_segment_distance(opponents, np.array([x, y]), np.array([PITCH_LENGTH, PITCH_WIDTH / 2]))
        blockers = int(np.sum((lane < 1.5) & (tpar > 0.05)))
    brk = expected_goals(x, y, header=header, pressure=pressure, situation=situation)
    factors = brk.factors()
    factors["nearest_defender_m"] = round(nearest, 1) if nearest is not None else None
    factors["defenders_in_shot_lane"] = blockers
    return brk.xg, factors


def pitch_control(home_xy: np.ndarray, away_xy: np.ndarray, home_vel: np.ndarray | None = None,
                  away_vel: np.ndarray | None = None, nx: int = 21, ny: int = 14) -> np.ndarray:
    """Simplified time-to-intercept pitch control (absolute coordinates).

    Returns an (ny, nx) grid with the probability that the *home* team controls each cell.
    """
    xs = (np.arange(nx) + 0.5) * PITCH_LENGTH / nx
    ys = (np.arange(ny) + 0.5) * PITCH_WIDTH / ny
    gx, gy = np.meshgrid(xs, ys)
    cells = np.stack([gx.ravel(), gy.ravel()], axis=1)

    def arrival(xy: np.ndarray, vel: np.ndarray | None) -> np.ndarray:
        start = xy + (vel * REACTION_S if vel is not None else 0.0)
        d = np.linalg.norm(cells[None, :, :] - start[:, None, :], axis=2)
        return (REACTION_S + d / MAX_RUN_MPS).min(axis=0)

    t_home = arrival(home_xy, home_vel)
    t_away = arrival(away_xy, away_vel)
    p_home = 1.0 / (1.0 + np.exp(-(t_away - t_home) / 0.45))
    return p_home.reshape(ny, nx)


def control_share(grid: np.ndarray, home_attack_dir: int) -> dict[str, float]:
    """Summaries of a pitch-control grid: overall share and share of the attacking half for each side."""
    nx = grid.shape[1]
    home_attacking_half = grid[:, nx // 2:] if home_attack_dir == 1 else grid[:, : nx // 2]
    away_attacking_half = grid[:, : nx // 2] if home_attack_dir == 1 else grid[:, nx // 2:]
    return {
        "home_total": round(float(grid.mean()), 3),
        "home_in_attacking_half": round(float(home_attacking_half.mean()), 3),
        "away_in_attacking_half": round(float(1 - away_attacking_half.mean()), 3),
    }
