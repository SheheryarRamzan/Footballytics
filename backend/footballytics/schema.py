"""Footballytics Event Protocol (FEP) v1: the wire format for synthetic match events.

Design choices:
* Absolute pitch coordinates in metres (105 x 68, origin bottom-left) so events line up
  with tracking frames and on-screen overlays. ``attack_dir`` on each event says which way
  the acting team attacks (+1 = towards x=105), so consumers can normalise.
* Events are emitted when their outcome is *known* (a pass is published when it arrives),
  which mirrors real live data feeds and keeps the stream causally honest.
* Types map cleanly onto SPADL / StatsBomb concepts so standard tooling can consume exports.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = "fep/1.0"


class EventType(StrEnum):
    MATCH_START = "match_start"
    PERIOD_START = "period_start"
    PERIOD_END = "period_end"
    MATCH_END = "match_end"
    KICK_OFF = "kick_off"
    PASS = "pass"
    CROSS = "cross"
    CARRY = "carry"
    TAKE_ON = "take_on"
    PRESSURE = "pressure"
    TACKLE = "tackle"
    INTERCEPTION = "interception"
    CLEARANCE = "clearance"
    BALL_RECOVERY = "ball_recovery"
    SHOT = "shot"
    GOAL = "goal"
    KEEPER_SAVE = "keeper_save"
    FOUL = "foul"
    CARD = "card"
    OFFSIDE = "offside"
    BALL_OUT = "ball_out"
    THROW_IN = "throw_in"
    CORNER = "corner"
    FREE_KICK = "free_kick"
    GOAL_KICK = "goal_kick"
    PENALTY_AWARDED = "penalty_awarded"
    SUBSTITUTION = "substitution"
    SPRINT = "sprint"


class Event(BaseModel):
    schema_version: str = SCHEMA_VERSION
    event_id: str
    match_id: str
    seq: int
    t: float = Field(description="Seconds of play since kick-off (monotonic, excludes half-time).")
    period: int
    clock: float = Field(description="Match clock in seconds as displayed (2nd half starts at 2700).")
    type: EventType
    team_id: str | None = None
    player_id: str | None = None
    x: float | None = None
    y: float | None = None
    end_x: float | None = None
    end_y: float | None = None
    outcome: str | None = None
    receiver_id: str | None = None
    possession: int | None = None
    attack_dir: int | None = None
    under_pressure: bool = False
    qualifiers: dict[str, Any] = Field(default_factory=dict)

    @property
    def minute(self) -> int:
        return int(self.clock // 60) + 1


def public_event(event: dict) -> dict:
    """Strip simulator ground-truth fields (qualifier keys starting with "_") before publishing."""
    q = event.get("qualifiers") or {}
    if not any(k.startswith("_") for k in q):
        return event
    return {**event, "qualifiers": {k: v for k, v in q.items() if not k.startswith("_")}}


class TrackingFrame(BaseModel):
    """10 Hz positions. ``players`` rows are [player_id, x, y, speed_mps]."""

    match_id: str
    frame: int
    t: float
    period: int
    clock: float
    ball: tuple[float, float, float]
    ball_owner: str | None = None
    players: list[tuple[str, float, float, float]]


class MatchMeta(BaseModel):
    match_id: str
    home: str
    away: str
    home_name: str
    away_name: str
    venue: str
    kickoff_label: str
    seed: int
    home_lineup: list[str]
    away_lineup: list[str]
    home_subs: list[str]
    away_subs: list[str]
    home_formation: str
    away_formation: str
