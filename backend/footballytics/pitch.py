"""Pitch geometry shared by the simulator and the stats engine.

Coordinates are metres on a 105 x 68 pitch, origin at the bottom-left corner.
"Team frame" means the coordinates are flipped so the team attacks towards x = 105.
"""

from __future__ import annotations

import math

import numpy as np

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0
HALF_LENGTH = PITCH_LENGTH / 2
CENTER = (HALF_LENGTH, PITCH_WIDTH / 2)
GOAL_HALF_WIDTH = 7.32 / 2
GOAL_Y_LOW = PITCH_WIDTH / 2 - GOAL_HALF_WIDTH
GOAL_Y_HIGH = PITCH_WIDTH / 2 + GOAL_HALF_WIDTH
BOX_DEPTH = 16.5
BOX_Y_LOW = PITCH_WIDTH / 2 - 20.16
BOX_Y_HIGH = PITCH_WIDTH / 2 + 20.16
SIX_YARD_DEPTH = 5.5
PENALTY_SPOT_X = PITCH_LENGTH - 11.0


def to_team_frame(x: float, y: float, direction: int) -> tuple[float, float]:
    """Convert absolute coordinates to the frame where the team attacks towards x = 105."""
    if direction == 1:
        return x, y
    return PITCH_LENGTH - x, PITCH_WIDTH - y


def to_team_frame_arr(xy: np.ndarray, direction: int) -> np.ndarray:
    if direction == 1:
        return xy
    out = np.empty_like(xy)
    out[..., 0] = PITCH_LENGTH - xy[..., 0]
    out[..., 1] = PITCH_WIDTH - xy[..., 1]
    return out


def distance_to_goal(x: float, y: float) -> float:
    """Distance to the centre of the goal being attacked (team frame)."""
    return math.hypot(PITCH_LENGTH - x, PITCH_WIDTH / 2 - y)


def goal_opening_angle(x: float, y: float) -> float:
    """Angle (radians) subtended by the goal mouth from (x, y), team frame."""
    a = math.atan2(GOAL_Y_HIGH - y, PITCH_LENGTH - x)
    b = math.atan2(GOAL_Y_LOW - y, PITCH_LENGTH - x)
    return abs(a - b)


def in_box(x: float, y: float) -> bool:
    """True when (x, y) is inside the attacked penalty box (team frame)."""
    return x >= PITCH_LENGTH - BOX_DEPTH and BOX_Y_LOW <= y <= BOX_Y_HIGH


def zone_name(x: float, y: float) -> str:
    """Human-readable pitch zone in team frame, used in narratives."""
    third = "defensive third" if x < 35 else "middle third" if x < 70 else "final third"
    if in_box(x, y):
        return "penalty box"
    lane = "left" if y > 45.3 else "right" if y < 22.7 else "central"
    return f"{lane} {third}"


def point_segment_distance(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Distance from each point to segment a-b and the projection parameter t in [0, 1]."""
    ab = b - a
    denom = float(ab @ ab)
    if denom < 1e-9:
        d = np.linalg.norm(points - a, axis=1)
        return d, np.zeros(len(points))
    t = np.clip(((points - a) @ ab) / denom, 0.0, 1.0)
    proj = a + t[:, None] * ab
    return np.linalg.norm(points - proj, axis=1), t


def clamp_to_pitch(xy: np.ndarray, margin: float = 0.0) -> np.ndarray:
    xy[..., 0] = np.clip(xy[..., 0], margin, PITCH_LENGTH - margin)
    xy[..., 1] = np.clip(xy[..., 1], margin, PITCH_WIDTH - margin)
    return xy
