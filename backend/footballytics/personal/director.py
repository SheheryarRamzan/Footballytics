"""Personal Director: produces a different live show for every fan across all concurrent matches.

For each incoming moment it scores *personal relevance* from
  * the moment's match importance (leverage-weighted by the stats engine),
  * the fan's learned taste for that kind of moment (Taste Learner weights),
  * involvement of the fan's fantasy squad (captain counts double) and favourite club,
and then decides, under an interruption budget, whether to
  CUT    the main stage to that match,
  PIP    show it picture-in-picture without leaving the current match,
  TICKER put a line in the personal ticker, or ignore it.
Every decision carries its reasons, so the UI can answer "why am I seeing this?".
It also turns fantasy ledger entries for the fan's squad into personal points updates.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..league import League
from .profiles import FanProfile

CUT_AT, PIP_AT, TICKER_AT = 0.78, 0.5, 0.3
MIN_CUT_GAP_S = 18.0  # wall-clock seconds between cuts (interruption budget)
HOLD_S = 22.0  # how long to stay on a cut match before returning home

ROLE_WORDS = {"GK": "keeper", "DEF": "defender", "MID": "midfielder", "FWD": "forward"}


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


@dataclass
class Decision:
    action: str  # cut | pip | ticker | return | points
    match_id: str
    relevance: float
    reasons: list[str]
    line: str
    moment_id: str | None = None
    kind: str | None = None
    minute: int | None = None
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class PersonalDirector:
    def __init__(self, fan: FanProfile, league: League, home_match: str | None, matches: dict[str, dict]):
        self.fan = fan
        self.league = league
        self.matches = matches  # match_id -> {home, away}
        self.home_match = home_match
        self.stage = home_match
        self.last_cut = 0.0
        self.cut_until = 0.0
        self.points: dict[str, int] = {}

    # ------------------------------------------------------------------ helpers
    @property
    def squad(self) -> set[str]:
        return set(self.fan.squad)

    def _name(self, pid: str) -> str:
        p = self.league.players.get(pid)
        return p.name if p else pid

    def _who(self, pid: str) -> str:
        p = self.league.players.get(pid)
        if p is None:
            return pid
        if pid == self.fan.captain:
            return f"your captain {p.name}"
        if pid in self.squad:
            return f"your {ROLE_WORDS[p.group]} {p.name}"
        return p.name

    def match_involves_club(self, match_id: str) -> bool:
        m = self.matches.get(match_id, {})
        return self.fan.favorite_club in (m.get("home"), m.get("away"))

    def squad_in_match(self, match_id: str) -> list[str]:
        m = self.matches.get(match_id, {})
        clubs = {m.get("home"), m.get("away")}
        return [p for p in self.fan.squad if self.league.players[p].club_id in clubs]

    # ------------------------------------------------------------------ relevance
    def relevance(self, moment: dict) -> tuple[float, list[str]]:
        kind = moment["kind"]
        w = self.fan.weights.get(kind, 0.3)
        rel = moment["importance"] / 100.0 * w
        reasons = [f"{kind.replace('_', ' ')} (match importance {moment['importance']:.0f}, your weight {w:.2f})"]
        involved = [p for p in moment.get("player_ids", []) if p in self.squad]
        if self.fan.captain in involved:
            rel += 0.6
            reasons.append(f"your captain {self._name(self.fan.captain)} is involved")
        elif involved:
            rel += 0.35
            reasons.append(f"{', '.join(self._name(p) for p in involved)} {'is' if len(involved) == 1 else 'are'} in your squad")
        if self.fan.focus_player and self.fan.focus_player in moment.get("player_ids", []):
            rel += 0.4
            reasons.append(f"you're following {self._name(self.fan.focus_player)} on Player Cam")
        if moment.get("team_id") == self.fan.favorite_club:
            rel += 0.3
            reasons.append(f"{self.league.clubs[self.fan.favorite_club].name} is your club")
        elif self.match_involves_club(moment["match_id"]):
            rel += 0.1
            reasons.append("your club's match")
        n = len(self.squad_in_match(moment["match_id"]))
        if n and not involved:
            rel += min(0.15, 0.05 * n)
            reasons.append(f"{n} of your players are in this match")
        return round(min(1.5, rel), 3), reasons

    # ------------------------------------------------------------------ decisions
    def on_moment(self, moment: dict, now: float | None = None) -> list[Decision]:
        now = now or time.time()
        out: list[Decision] = []
        if moment["kind"] in ("kick_off",):
            return out
        rel, reasons = self.relevance(moment)
        mid = moment["match_id"]
        line = self.personal_line(moment)
        players = moment.get("player_ids", [])
        # player + facts let clients build a language-neutral line for non-English viewers
        base = dict(match_id=mid, relevance=rel, reasons=reasons, line=line, moment_id=moment["moment_id"],
                    kind=moment["kind"], minute=moment.get("minute"),
                    data={"player_id": players[0] if players else None, "facts": moment.get("facts", {})})
        personal = any(p in self.squad for p in moment.get("player_ids", [])) or             self.match_involves_club(mid)
        must_cut = personal and rel >= 1.0 and moment["kind"] in ("goal", "wonder_strike", "penalty_awarded",
                                                                   "red_card")
        if mid != self.stage and rel >= CUT_AT and (now - self.last_cut >= MIN_CUT_GAP_S or must_cut):
            self.stage, self.last_cut, self.cut_until = mid, now, now + HOLD_S
            out.append(Decision("cut", **base))
        elif mid != self.stage and rel >= PIP_AT:
            out.append(Decision("pip", **base))
        elif rel >= TICKER_AT or mid == self.stage:
            out.append(Decision("ticker", **base))
        return out

    def on_tick(self, now: float | None = None) -> list[Decision]:
        """Return to the fan's home match once a cut has been held long enough."""
        now = now or time.time()
        if self.stage != self.home_match and self.cut_until and now >= self.cut_until and self.home_match:
            self.stage, self.cut_until = self.home_match, 0.0
            return [Decision("return", self.home_match, 0.0, ["cut finished: back to your club's match"],
                             "Back to your match.")]
        return []

    def on_fantasy(self, match_id: str, entries: list[dict]) -> list[Decision]:
        out = []
        for e in entries:
            pid = e["player_id"]
            if pid not in self.squad or e.get("provisional"):
                continue
            mult = 2 if pid == self.fan.captain else 1
            pts = e["points"] * mult
            self.points[pid] = self.points.get(pid, 0) + pts
            total = sum(self.points.values())
            sign = "+" if pts >= 0 else ""
            cap = " (captain x2)" if mult == 2 else ""
            line = f"{sign}{pts} {self._name(pid)}: {e['reason']}{cap}."
            out.append(Decision("points", match_id, 0.0, [f"{self._name(pid)} is in your squad"], line,
                                data={"player_id": pid, "points": pts, "reason": e["reason"], "total": total,
                                      "event_id": e.get("event_id")}))
        return out

    def stage_switch(self, match_id: str) -> None:
        """The fan chose a match manually: respect it (no auto-return for a while)."""
        self.stage = match_id
        self.home_match = match_id
        self.cut_until = 0.0
        self.last_cut = time.time()

    # ------------------------------------------------------------------ words
    def personal_line(self, m: dict) -> str:
        players = m.get("player_ids", [])
        who = self._who(players[0]) if players else None
        f = m.get("facts", {})
        k = m["kind"]
        cap = (m.get("caption") or {}).get("fan", "")
        if not who:
            return cap
        if k in ("goal", "wonder_strike"):
            return f"GOAL! {_cap(who)} scores. {f.get('score', '')}"
        if k == "big_chance":
            return f"{_cap(who)} goes close (xG {f.get('xg', 0):.2f})."
        if k == "great_save":
            return f"Huge save from {who}."
        if k == "sprint_tag":
            return f"{_cap(who)} hits {f.get('speed_kmh', 0):.1f} km/h."
        if k == "line_breaking_pass":
            return f"{_cap(who)} splits {f.get('defenders_bypassed', 0)} defenders with one pass."
        if k == "high_turnover":
            return f"{_cap(who)} wins it back high up the pitch."
        if k == "penalty_awarded":
            return f"Penalty! {_cap(who)} is fouled."
        if k in ("yellow_card", "red_card"):
            return f"{'Yellow' if k == 'yellow_card' else 'RED'} card for {who}."
        if k == "milestone":
            return f.get("text", cap)
        return cap
