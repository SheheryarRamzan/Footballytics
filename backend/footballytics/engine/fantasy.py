"""Live fantasy points with an auditable ledger (every point links to the event that earned it).

Rules (our own fictional fantasy game, modelled on familiar formats):
  appearance 1 (+1 at 60 min) | goal GK/DEF 6, MID 5, FWD 4 | assist 3
  clean sheet (60+ min) GK/DEF 4, MID 1 | every 3 saves 1 | penalty save 5 | penalty miss -2
  every 2 conceded (GK/DEF) -1 | yellow -1 | red -3
  defensive contribution: DEF 10 clearances/blocks/interceptions/tackles -> 2,
                          MID/FWD 12 of those + ball recoveries -> 2
  bonus 3/2/1 for the top three Impact Scores in the match (projected live)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

GOAL_POINTS = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}
CLEAN_SHEET_POINTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}


@dataclass
class LedgerEntry:
    player_id: str
    points: int
    reason: str
    clock: float
    event_id: str | None = None
    provisional: bool = False

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class PlayerFantasy:
    player_id: str
    group: str
    team_id: str
    on_at: float = 0.0
    off_at: float | None = None
    goals_conceded: int = 0
    saves: int = 0
    def_actions: int = 0
    recoveries: int = 0
    def_bonus_awarded: bool = False
    entries: list[LedgerEntry] = field(default_factory=list)

    @property
    def confirmed(self) -> int:
        return sum(e.points for e in self.entries if not e.provisional)


class FantasyLedger:
    """Tracks live fantasy points for every player in one match."""

    def __init__(self, groups: dict[str, str], teams: dict[str, str]):
        self.groups = groups  # player_id -> GK/DEF/MID/FWD
        self.teams = teams  # player_id -> team_id
        self.players: dict[str, PlayerFantasy] = {}
        self.clock = 0.0

    # -------------------------------------------------------------- lifecycle
    def start(self, player_id: str, clock: float) -> None:
        pf = PlayerFantasy(player_id, self.groups[player_id], self.teams[player_id], on_at=clock)
        self.players[player_id] = pf
        self._add(pf, 1, "appearance", clock)

    def _add(self, pf: PlayerFantasy, pts: int, reason: str, clock: float, event_id: str | None = None) -> LedgerEntry:
        entry = LedgerEntry(pf.player_id, pts, reason, clock, event_id)
        pf.entries.append(entry)
        return entry

    def minutes(self, pf: PlayerFantasy) -> float:
        end = pf.off_at if pf.off_at is not None else self.clock
        return max(0.0, (end - pf.on_at) / 60.0)

    # -------------------------------------------------------------- events
    def on_event(self, e: dict) -> list[LedgerEntry]:
        """Apply one event; returns the new ledger entries (used for live notifications)."""
        self.clock = max(self.clock, e["clock"])
        new: list[LedgerEntry] = []
        new += self._tick_minutes()
        t, pid, et = e["clock"], e.get("player_id"), e["type"]
        pf = self.players.get(pid) if pid else None
        if et == "substitution" and pf:
            pf.off_at = t
            new_id = e["qualifiers"]["replacement_id"]
            self.start(new_id, t)
            new.append(self.players[new_id].entries[-1])
        elif et == "goal" and pf:
            new.append(self._add(pf, GOAL_POINTS[pf.group], "goal", t, e["event_id"]))
            assist = e["qualifiers"].get("assist_id")
            if assist and assist in self.players:
                new.append(self._add(self.players[assist], 3, "assist", t, e["event_id"]))
            conceding = [p for p in self.players.values() if p.team_id != pf.team_id and p.off_at is None]
            for p in conceding:
                p.goals_conceded += 1
                if p.group in ("GK", "DEF") and p.goals_conceded % 2 == 0:
                    new.append(self._add(p, -1, "2 goals conceded", t, e["event_id"]))
        elif et == "keeper_save" and pf:
            pf.saves += 1
            if pf.saves % 3 == 0:
                new.append(self._add(pf, 1, "3 saves", t, e["event_id"]))
        elif et == "card" and pf:
            pts = -1 if e["outcome"] == "yellow" else -3
            if e["outcome"] == "second_yellow":
                pts = -2  # -1 already taken for the first yellow
            new.append(self._add(pf, pts, f"{e['outcome'].replace('_', ' ')} card", t, e["event_id"]))
            if e["outcome"] != "yellow":
                pf.off_at = t
        elif et == "shot" and pf and e["qualifiers"].get("situation") == "penalty" and e["outcome"] != "goal":
            new.append(self._add(pf, -2, "penalty missed", t, e["event_id"]))
            if e["outcome"] == "saved":
                keeper = next((p for p in self.players.values()
                               if p.team_id != pf.team_id and p.group == "GK" and p.off_at is None), None)
                if keeper:
                    new.append(self._add(keeper, 5, "penalty saved", t, e["event_id"]))
        if pf and et in ("tackle", "interception", "clearance") and (et != "tackle" or e["outcome"] == "won"):
            pf.def_actions += 1
        if pf and et == "ball_recovery":
            pf.recoveries += 1
        if pf and not pf.def_bonus_awarded:
            need, count = (10, pf.def_actions) if pf.group == "DEF" else (12, pf.def_actions + pf.recoveries)
            if pf.group != "GK" and count >= need:
                pf.def_bonus_awarded = True
                new.append(self._add(pf, 2, "defensive contribution", t, e["event_id"]))
        return new

    def _tick_minutes(self) -> list[LedgerEntry]:
        new = []
        for pf in self.players.values():
            if pf.off_at is None and self.minutes(pf) >= 60 and not any(x.reason == "60 minutes" for x in pf.entries):
                new.append(self._add(pf, 1, "60 minutes", self.clock))
        return new

    # -------------------------------------------------------------- views
    def provisional(self, pf: PlayerFantasy, finished: bool) -> list[LedgerEntry]:
        """Clean-sheet points that are on course (or locked in at full time)."""
        if pf.group == "FWD" or pf.goals_conceded > 0:
            return []
        played_60 = self.minutes(pf) >= 60
        # Live: show it once the player has played 60, or is still on in the second half (on course).
        eligible = played_60 if finished else (played_60 or (pf.off_at is None and self.clock >= 45 * 60))
        if not eligible:
            return []
        return [LedgerEntry(pf.player_id, CLEAN_SHEET_POINTS[pf.group], "clean sheet", self.clock,
                            provisional=not finished)]

    def totals(self, impact: dict[str, float], finished: bool = False) -> dict[str, dict]:
        """Per-player totals including provisional clean sheet and projected bonus."""
        ranked = sorted(impact.items(), key=lambda kv: -kv[1])[:3]
        bonus = {pid: pts for (pid, _), pts in zip(ranked, (3, 2, 1))}
        out = {}
        for pid, pf in self.players.items():
            entries = pf.entries + self.provisional(pf, finished)
            if pid in bonus:
                entries = entries + [LedgerEntry(pid, bonus[pid], "bonus (impact)", self.clock,
                                                 provisional=not finished)]
            out[pid] = {
                "player_id": pid,
                "points": sum(e.points for e in entries),
                "confirmed": pf.confirmed,
                "breakdown": [e.to_dict() for e in entries],
                "minutes": round(self.minutes(pf), 1),
            }
        return out


def group_counts(entries: list[LedgerEntry]) -> dict[str, int]:
    c: dict[str, int] = defaultdict(int)
    for e in entries:
        c[e.reason] += e.points
    return dict(c)
