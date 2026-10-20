"""Fan profiles: favourite club, fantasy squad, viewing mode, language and learned taste."""

from __future__ import annotations

import random
import uuid
from dataclasses import asdict, dataclass, field

from ..league import League

MODES = ("fan", "analyst", "kids", "audio")
SQUAD_SHAPE = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
BUDGET = 100.0
MAX_PER_CLUB = 3

# How much each moment kind matters per viewing mode (the Taste Learner adapts these per fan).
MODE_WEIGHTS: dict[str, dict[str, float]] = {
    "fan": {"goal": 1.0, "wonder_strike": 1.0, "penalty_awarded": 1.0, "red_card": 0.9, "big_chance": 0.9,
            "great_save": 0.8, "milestone": 0.8, "full_time": 0.9, "half_time": 0.7, "momentum_swing": 0.5,
            "sprint_tag": 0.5, "shot_speed": 0.5, "high_turnover": 0.45, "line_breaking_pass": 0.45,
            "control_shift": 0.35, "pressing_shift": 0.3, "tempo_shift": 0.2, "yellow_card": 0.3,
            "substitution": 0.2, "kick_off": 0.3},
    "analyst": {"goal": 1.0, "wonder_strike": 1.0, "penalty_awarded": 0.9, "red_card": 0.9, "big_chance": 0.9,
                "great_save": 0.6, "milestone": 0.5, "full_time": 0.9, "half_time": 0.8, "momentum_swing": 0.75,
                "sprint_tag": 0.3, "shot_speed": 0.35, "high_turnover": 0.7, "line_breaking_pass": 0.8,
                "control_shift": 0.85, "pressing_shift": 0.85, "tempo_shift": 0.6, "yellow_card": 0.25,
                "substitution": 0.4, "kick_off": 0.2},
    "kids": {"goal": 1.0, "wonder_strike": 1.0, "penalty_awarded": 0.9, "red_card": 0.6, "big_chance": 0.8,
             "great_save": 0.9, "milestone": 0.8, "full_time": 0.8, "half_time": 0.6, "momentum_swing": 0.3,
             "sprint_tag": 0.8, "shot_speed": 0.8, "high_turnover": 0.3, "line_breaking_pass": 0.4,
             "control_shift": 0.15, "pressing_shift": 0.1, "tempo_shift": 0.1, "yellow_card": 0.4,
             "substitution": 0.2, "kick_off": 0.4},
}
MODE_WEIGHTS["audio"] = dict(MODE_WEIGHTS["fan"])


@dataclass
class FanProfile:
    fan_id: str
    display_name: str = "Fan"
    favorite_club: str = "RIV"
    squad: list[str] = field(default_factory=list)
    captain: str | None = None
    vice_captain: str | None = None
    mode: str = "fan"
    language: str = "en"
    focus_player: str | None = None  # Player Cam
    weights: dict[str, float] = field(default_factory=dict)
    signals: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.weights:
            self.weights = dict(MODE_WEIGHTS.get(self.mode, MODE_WEIGHTS["fan"]))

    def to_dict(self) -> dict:
        return asdict(self)


def auto_squad(league: League, favorite_club: str | None = None, seed: int | None = None) -> tuple[list[str], str, str]:
    """A valid 15-player fantasy squad (2 GK, 5 DEF, 5 MID, 3 FWD, budget 100, max 3 per club).

    Greedy by value with randomness; leans towards the favourite club. Returns (squad, captain, vice).
    """
    rng = random.Random(seed)
    for _ in range(200):
        squad, spent, per_club = [], 0.0, {}
        remaining = dict(SQUAD_SHAPE)
        pool = list(league.players.values())
        rng.shuffle(pool)
        # value = rating per price, with a bonus for the favourite club and some noise
        pool.sort(key=lambda p: -((p.rating / p.price) * (1.25 if p.club_id == favorite_club else 1.0)
                                  * rng.uniform(0.85, 1.15)))
        stars = [p for p in sorted(pool, key=lambda p: -p.rating)[:30] if p.group in ("MID", "FWD")][:12]
        picks = rng.sample(stars, 2) + pool
        for p in picks:
            if remaining.get(p.group, 0) <= 0 or p.id in squad or per_club.get(p.club_id, 0) >= MAX_PER_CLUB:
                continue
            slots_left = sum(remaining.values()) - 1
            if spent + p.price + 4.0 * slots_left > BUDGET:
                continue
            squad.append(p.id)
            spent += p.price
            per_club[p.club_id] = per_club.get(p.club_id, 0) + 1
            remaining[p.group] -= 1
            if not any(remaining.values()):
                break
        if not any(remaining.values()):
            attackers = sorted((league.players[i] for i in squad if league.players[i].group in ("MID", "FWD")),
                               key=lambda p: -p.rating)
            return squad, attackers[0].id, attackers[1].id
    raise RuntimeError("could not build a valid squad")


def validate_squad(league: League, squad: list[str]) -> list[str]:
    """Return a list of rule violations (empty when valid)."""
    errors = []
    if len(set(squad)) != 15:
        errors.append("squad must have 15 different players")
    groups: dict[str, int] = {}
    clubs: dict[str, int] = {}
    cost = 0.0
    for pid in squad:
        p = league.players.get(pid)
        if p is None:
            errors.append(f"unknown player {pid}")
            continue
        groups[p.group] = groups.get(p.group, 0) + 1
        clubs[p.club_id] = clubs.get(p.club_id, 0) + 1
        cost += p.price
    if groups != SQUAD_SHAPE and not errors:
        errors.append(f"squad shape must be {SQUAD_SHAPE}, got {groups}")
    if cost > BUDGET + 1e-6:
        errors.append(f"budget exceeded: {cost:.1f} > {BUDGET}")
    over = [c for c, n in clubs.items() if n > MAX_PER_CLUB]
    if over:
        errors.append(f"max {MAX_PER_CLUB} players per club: {over}")
    return errors


class ProfileStore:
    """In-memory store (swapped for Cosmos DB in Azure, same interface)."""

    def __init__(self, league: League):
        self.league = league
        self._fans: dict[str, FanProfile] = {}

    def create(self, favorite_club: str = "RIV", mode: str = "fan", language: str = "en",
               display_name: str = "Fan", squad: list[str] | None = None, captain: str | None = None) -> FanProfile:
        fan_id = uuid.uuid4().hex[:12]
        if squad:
            errors = validate_squad(self.league, squad)
            if errors:
                raise ValueError("; ".join(errors))
            vice = next((p for p in squad if p != captain), None)
        else:
            squad, auto_captain, vice = auto_squad(self.league, favorite_club, seed=hash(fan_id) & 0xFFFF)
            captain = captain or auto_captain
        fan = FanProfile(fan_id, display_name, favorite_club, squad, captain, vice,
                         mode if mode in MODES else "fan", language)
        self._fans[fan_id] = fan
        return fan

    def get(self, fan_id: str) -> FanProfile:
        if fan_id not in self._fans:
            raise KeyError(f"unknown fan {fan_id}")
        return self._fans[fan_id]

    def update(self, fan_id: str, **changes) -> FanProfile:
        fan = self.get(fan_id)
        if "mode" in changes and changes["mode"] in MODES and changes["mode"] != fan.mode:
            old, fan.mode = fan.mode, changes.pop("mode")
            # Switching mode changes the prior but keeps what the Taste Learner learned about this fan.
            learned = {k: v / (MODE_WEIGHTS[old].get(k) or 1.0) for k, v in fan.weights.items()}
            fan.weights = {k: round(v * min(2.0, max(0.5, learned.get(k, 1.0))), 3)
                           for k, v in MODE_WEIGHTS[fan.mode].items()}
        for key in ("display_name", "favorite_club", "language", "captain", "vice_captain", "focus_player"):
            if key in changes and changes[key] is not None:
                setattr(fan, key, changes[key])
        return fan
