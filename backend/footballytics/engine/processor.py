"""MatchProcessor: the deterministic "Interpret" stage for one live match.

Feed it tracking frames (10 Hz) and events as they arrive; it maintains team and player
statistics, rolling tactical indicators, live fantasy points, and emits ``Moment`` objects.
Everything here is fast (well under a millisecond per frame) and fully explainable.
"""

from __future__ import annotations

import bisect
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np

from ..league import League
from ..pitch import PITCH_LENGTH, distance_to_goal, to_team_frame, to_team_frame_arr
from .fantasy import FantasyLedger, LedgerEntry
from .metrics import SPRINT_KMH, TAG_SPEED_KMH, assess_pass, shot_xg
from .moments import Moment, finalize

IN_PLAY_TYPES = {"pass", "cross", "carry", "take_on", "tackle", "interception", "clearance", "ball_recovery",
                 "shot", "pressure", "foul"}


@dataclass
class TeamStats:
    passes: int = 0
    passes_completed: int = 0
    final_third_passes: int = 0
    shots: int = 0
    shots_on_target: int = 0
    big_chances: int = 0
    goals: int = 0
    xg: float = 0.0
    xt: float = 0.0
    possession_s: float = 0.0
    corners: int = 0
    fouls: int = 0
    yellow: int = 0
    red: int = 0
    offsides: int = 0
    tackles_won: int = 0
    interceptions: int = 0
    recoveries: int = 0
    high_turnovers: int = 0
    distance_m: float = 0.0

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["pass_completion"] = round(self.passes_completed / self.passes, 3) if self.passes else None
        d["xg"] = round(float(self.xg), 2)
        d["xt"] = round(float(self.xt), 3)
        d["distance_km"] = round(self.distance_m / 1000, 1)
        return d


@dataclass
class PlayerStats:
    player_id: str
    team_id: str
    passes: int = 0
    passes_completed: int = 0
    key_passes: int = 0
    assists: int = 0
    xa: float = 0.0
    xt_added: float = 0.0
    xg: float = 0.0
    shots: int = 0
    goals: int = 0
    touches: int = 0
    tackles_won: int = 0
    interceptions: int = 0
    recoveries: int = 0
    take_ons: int = 0
    take_ons_won: int = 0
    saves: int = 0
    difficult_passes: int = 0
    line_breaks: int = 0  # completed passes past 3+ defenders
    difficulty_sum: float = 0.0
    accuracy_sum: float = 0.0
    accuracy_n: int = 0
    distance_m: float = 0.0
    top_speed_kmh: float = 0.0
    top_shot_speed_kmh: float = 0.0
    sprints: int = 0
    yellow: int = 0
    red: int = 0

    @property
    def impact(self) -> float:
        return (8 * self.xg + 25 * self.xt_added + 4 * self.goals + 3 * self.assists + 3 * self.xa
                + 0.6 * self.key_passes + 0.35 * (self.tackles_won + self.interceptions + self.recoveries)
                + 0.5 * self.saves + 0.15 * self.difficult_passes - 0.8 * self.yellow - 3 * self.red)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["impact"] = round(self.impact, 2)
        d["xg"] = round(float(self.xg), 2)
        d["xa"] = round(float(self.xa), 2)
        d["xt_added"] = round(float(self.xt_added), 3)
        d["distance_km"] = round(self.distance_m / 1000, 2)
        d["avg_pass_difficulty"] = round(self.difficulty_sum / self.passes, 1) if self.passes else None
        d["avg_pass_placement"] = round(self.accuracy_sum / self.accuracy_n, 0) if self.accuracy_n else None
        d["pass_accuracy"] = round(self.passes_completed / self.passes, 3) if self.passes else None
        for k in ("difficulty_sum", "accuracy_sum", "accuracy_n"):
            d.pop(k)
        d["top_speed_kmh"] = round(self.top_speed_kmh, 1)
        d["top_shot_speed_kmh"] = round(self.top_shot_speed_kmh, 1)
        return d


@dataclass
class _Window:
    """Lightweight record of in-play events for rolling tactical indicators."""
    clock: float
    type: str
    team: str | None
    outcome: str | None
    x_tf: float | None  # x in the acting team's frame
    length: float | None
    threat: float = 0.0
    possession: int | None = None


@dataclass
class Update:
    moments: list[Moment] = field(default_factory=list)
    fantasy: list[LedgerEntry] = field(default_factory=list)


class MatchProcessor:
    def __init__(self, meta: dict, league: League, season_players: dict | None = None):
        self.meta = meta
        self.match_id = meta["match_id"]
        self.home, self.away = meta["home"], meta["away"]
        self.league = league
        self.season_players = season_players or {}
        self.names: dict[str, str] = {c.id: c.name for c in league.clubs.values()}
        self.names.update({p.id: p.short_name for p in league.players.values()})
        self.full_names = {p.id: p.name for p in league.players.values()}
        self.team_of = {p.id: p.club_id for p in league.players.values()}
        groups = {p.id: p.group for p in league.players.values()}
        self.fantasy = FantasyLedger(groups, self.team_of)
        self.teams = {self.home: TeamStats(), self.away: TeamStats()}
        self.players: dict[str, PlayerStats] = {}
        self.score = {self.home: 0, self.away: 0}
        self.clock = 0.0
        self.period = 1
        self.home_attack_dir = 1
        self.finished = False

        self.frames: deque[dict] = deque(maxlen=400)
        self._frame_ts: deque[float] = deque(maxlen=400)
        self.last_frame: dict | None = None
        self.events: list[dict] = []
        self.moments: list[Moment] = []
        self.window: list[_Window] = []
        self.momentum: list[dict] = []
        self.regime = "balanced"
        self.regime_since = 0.0
        self._next_minute = 1
        self._last_swing = -999.0
        self._momentum_leader: str | None = None
        self._last_tag: dict[str, float] = {}
        self._in_sprint: dict[str, bool] = {}
        self._sprint_start: dict[str, float] = {}
        self._regime_candidate: tuple[str, int] = ("balanced", 0)
        self._last_turnover_moment = defaultdict(lambda: -999.0)
        self._last_line_breaker = defaultdict(lambda: -999.0)
        self._last_shift: dict[tuple[str, str], float] = defaultdict(lambda: -999.0)
        self._last_pass_by_possession: dict[int, dict] = {}
        self._pending_shot: dict | None = None

    # ------------------------------------------------------------------ helpers
    def ps(self, pid: str) -> PlayerStats:
        if pid not in self.players:
            self.players[pid] = PlayerStats(pid, self.team_of.get(pid, "?"))
        return self.players[pid]

    def other(self, team: str) -> str:
        return self.away if team == self.home else self.home

    def attack_dir(self, team: str) -> int:
        return self.home_attack_dir if team == self.home else -self.home_attack_dir

    def frame_at(self, t: float) -> dict | None:
        if not self.frames:
            return None
        i = bisect.bisect_left(self._frame_ts, t)
        cands = [j for j in (i - 1, i) if 0 <= j < len(self.frames)]
        j = min(cands, key=lambda j: abs(self._frame_ts[j] - t))
        return self.frames[j] if abs(self._frame_ts[j] - t) < 0.6 else None

    def positions(self, frame: dict | None, team: str) -> np.ndarray:
        if frame is None:
            return np.zeros((0, 2))
        pts = [(p[1], p[2]) for p in frame["players"] if self.team_of.get(p[0]) == team]
        return np.array(pts, dtype=float) if pts else np.zeros((0, 2))

    def score_text(self) -> str:
        return f"{self.names[self.home]} {self.score[self.home]}-{self.score[self.away]} {self.names[self.away]}"

    def _moment(self, kind: str, e_or_clock, team: str | None, players: list[str], facts: dict, why: list[str],
                evidence: list[str], update: Update, tags: list[str] | None = None) -> Moment:
        clock = e_or_clock["clock"] if isinstance(e_or_clock, dict) else e_or_clock
        t = e_or_clock["t"] if isinstance(e_or_clock, dict) else self.clock
        facts = {**facts, "minute": int(clock // 60) + 1, "score": self.score_text()}
        diff = self.score[self.home] - self.score[self.away]
        m = finalize(Moment(self.match_id, kind, clock, t, team, players, facts, why, evidence, tags=tags or []),
                     diff, self.names)
        self.moments.append(m)
        update.moments.append(m)
        return m

    # ------------------------------------------------------------------ frames
    def ingest_frame(self, frame: dict) -> Update:
        update = Update()
        prev = self.last_frame
        self.frames.append(frame)
        self._frame_ts.append(frame["t"])
        self.last_frame = frame
        self.clock = max(self.clock, frame["clock"])
        dt = frame["t"] - prev["t"] if prev else 0.0
        if prev is not None and 0 < dt < 0.5:
            prev_pos = {p[0]: (p[1], p[2]) for p in prev["players"]}
            owner = frame.get("ball_owner")
            if owner:
                self.teams.setdefault(self.team_of.get(owner, "?"), TeamStats()).possession_s += dt
            for pid, x, y, v in frame["players"]:
                st = self.ps(pid)
                if pid in prev_pos:
                    step = math.hypot(x - prev_pos[pid][0], y - prev_pos[pid][1])
                    if step < 2.0:
                        st.distance_m += step
                        self.teams[st.team_id].distance_m += step
                kmh = v * 3.6
                new_high = kmh > st.top_speed_kmh + 0.3
                if kmh > st.top_speed_kmh:
                    st.top_speed_kmh = kmh
                # A sprint is an effort of at least 1 s above the sprint threshold.
                started = self._sprint_start.get(pid)
                if kmh >= SPRINT_KMH:
                    if started is None:
                        self._sprint_start[pid] = frame["t"]
                    elif not self._in_sprint.get(pid) and frame["t"] - started >= 1.0:
                        self._in_sprint[pid] = True
                        st.sprints += 1
                elif kmh < SPRINT_KMH - 1.5:
                    self._sprint_start.pop(pid, None)
                    self._in_sprint[pid] = False
                # Tag only a new personal match-high above the threshold, and not too often.
                if (kmh >= TAG_SPEED_KMH and new_high and self.clock - self._last_tag.get(pid, -999) > 600
                        and self.clock - self._last_tag.get("_any", -999) > 45):
                    self._last_tag[pid] = self._last_tag["_any"] = self.clock
                    self._moment("sprint_tag", self.clock, st.team_id, [pid],
                                 {"speed_kmh": round(kmh, 1), "distance_km": round(st.distance_m / 1000, 2),
                                  "sprints": st.sprints, "x": x, "y": y},
                                 [f"{kmh:.1f} km/h is above the {TAG_SPEED_KMH:.0f} km/h tag threshold"], [], update,
                                 tags=["speed"])
        while self.clock >= self._next_minute * 60:
            self._on_minute(self._next_minute, update)
            self._next_minute += 1
        return update

    # ------------------------------------------------------------------ events
    def ingest_event(self, e: dict) -> Update:
        update = Update()
        self.events.append(e)
        self.clock = max(self.clock, e["clock"])
        et, team, pid = e["type"], e.get("team_id"), e.get("player_id")
        update.fantasy.extend(self._fantasy(e))
        x_tf = None
        if e.get("x") is not None and team:
            x_tf = to_team_frame(e["x"], e["y"], e["attack_dir"])[0]

        if et == "match_start":
            for p in self.meta.get("home_lineup", []) + self.meta.get("away_lineup", []):
                self.fantasy.start(p, 0.0)
                self.ps(p)
            self._moment("kick_off", e, None, [], {}, [], [e["event_id"]], update)
        elif et == "period_start":
            self.period = e["period"]
            self.home_attack_dir = e["qualifiers"].get("home_attack_dir", self.home_attack_dir)
        elif et == "period_end":
            kind = "half_time" if e["period"] == 1 else "full_time"
            if kind == "full_time":
                self.finished = True
            th, ta = self.teams[self.home], self.teams[self.away]
            self._moment(kind, e, None, [], {"xg_home": th.xg, "xg_away": ta.xg, "shots_home": th.shots,
                                              "shots_away": ta.shots}, [], [e["event_id"]], update)
        elif et in ("pass", "cross"):
            self._on_pass(e, update)
        elif et == "carry" and pid:
            st = self.ps(pid)
            st.touches += 1
            s = np.array(to_team_frame(e["x"], e["y"], e["attack_dir"]))
            en = np.array(to_team_frame(e["end_x"], e["end_y"], e["attack_dir"]))
            from ..models import expected_threat
            gain = expected_threat(en[0], en[1]) - expected_threat(s[0], s[1])
            if gain > 0:
                st.xt_added += gain
                self.teams[team].xt += gain
            self.window.append(_Window(e["clock"], et, team, None, x_tf, None, max(0.0, gain), e.get("possession")))
        elif et == "shot":
            self._on_shot(e, update)
        elif et == "goal":
            self._on_goal(e, update)
        elif et == "keeper_save":
            self.ps(pid).saves += 1
            shot = self._pending_shot
            if shot and (shot["xg"] >= 0.12 or shot["speed"] >= 95):
                self._moment("great_save", e, team, [pid], {"xg": round(shot["xg"], 3),
                             "shot_speed_kmh": round(shot["speed"], 0), "shooter_id": shot["player_id"]},
                             [f"denied a {shot['xg']:.2f} xG chance", f"shot at {shot['speed']:.0f} km/h"],
                             [shot["event_id"], e["event_id"]], update)
        elif et in ("tackle", "interception", "ball_recovery"):
            st = self.ps(pid)
            if et == "interception":
                st.interceptions += 1
                self.teams[team].interceptions += 1
            elif et == "ball_recovery":
                st.recoveries += 1
                self.teams[team].recoveries += 1
            elif e["outcome"] == "won":
                st.tackles_won += 1
                self.teams[team].tackles_won += 1
            self.window.append(_Window(e["clock"], et, team, e.get("outcome"), x_tf, None, 0.0, e.get("possession")))
            won = et != "tackle" or e["outcome"] == "won"
            if won and x_tf is not None and x_tf >= 70 and e["clock"] - self._last_turnover_moment[team] > 90:
                self._last_turnover_moment[team] = e["clock"]
                self.teams[team].high_turnovers += 1
                self._moment("high_turnover", e, team, [pid], {"metres_from_goal": round(PITCH_LENGTH - x_tf, 1)},
                             [f"won the ball {PITCH_LENGTH - x_tf:.0f} m from the opponent's goal"], [e["event_id"]],
                             update, tags=["pressing"])
        elif et == "take_on" and pid:
            st = self.ps(pid)
            st.take_ons += 1
            st.take_ons_won += e["outcome"] == "success"
            self.window.append(_Window(e["clock"], et, team, e["outcome"], x_tf, None, 0.0, e.get("possession")))
        elif et == "foul":
            self.teams[team].fouls += 1
            self.window.append(_Window(e["clock"], et, team, None, x_tf, None, 0.0, e.get("possession")))
        elif et == "card":
            st = self.ps(pid)
            if e["outcome"] == "yellow":
                st.yellow += 1
                self.teams[team].yellow += 1
                self._moment("yellow_card", e, team, [pid], {}, [], [e["event_id"]], update)
            else:
                st.red += 1
                self.teams[team].red += 1
                self._moment("red_card", e, team, [pid], {"reason": e["outcome"]},
                             [f"{self.names[team]} are down to {11 - self.teams[team].red} players"],
                             [e["event_id"]], update)
        elif et == "corner":
            self.teams[team].corners += 1
        elif et == "offside":
            self.teams[team].offsides += 1
        elif et == "penalty_awarded":
            self._moment("penalty_awarded", e, team, [pid] if pid else [], {"xg": 0.76},
                         ["penalties are converted about three times in four"], [e["event_id"]], update)
        elif et == "substitution":
            q = e["qualifiers"]
            self.ps(q["replacement_id"])
            self._moment("substitution", e, team, [q["replacement_id"], pid],
                         {"on_name": q["replacement_name"], "off_name": q["player_off_name"]}, [],
                         [e["event_id"]], update)
        if et in ("clearance", "pressure") and team:
            self.window.append(_Window(e["clock"], et, team, None, x_tf, None, 0.0, e.get("possession")))
        return update

    def _fantasy(self, e: dict) -> list[LedgerEntry]:
        if e["type"] == "match_start":
            return []
        return self.fantasy.on_event(e)

    def _on_pass(self, e: dict, update: Update) -> None:
        team, pid = e["team_id"], e["player_id"]
        st, ts = self.ps(pid), self.teams[team]
        st.passes += 1
        st.touches += 1
        ts.passes += 1
        complete = e["outcome"] == "complete"
        d = e["attack_dir"]
        start = np.array(to_team_frame(e["x"], e["y"], d))
        end = np.array(to_team_frame(e["end_x"], e["end_y"], d))
        frame = self.frame_at(e["t"])
        opp = to_team_frame_arr(self.positions(frame, self.other(team)), d) if frame else np.zeros((0, 2))
        recv_xy = None
        if complete and e.get("receiver_id") and self.last_frame:
            r = next((p for p in self.last_frame["players"] if p[0] == e["receiver_id"]), None)
            if r:
                recv_xy = np.array(to_team_frame(r[1], r[2], d))
        a = assess_pass(start, end, opp, lofted=e["qualifiers"].get("height") == "high", receiver_at_arrival=recv_xy)
        st.difficulty_sum += a.difficulty
        if a.accuracy is not None:
            st.accuracy_sum += a.accuracy
            st.accuracy_n += 1
        e["_assessment"] = {"difficulty": a.difficulty, "completion_prob": round(a.completion_prob, 3),
                            "placement": a.accuracy, "xt_added": round(float(a.xt_added), 4), **a.factors}
        if complete:
            st.passes_completed += 1
            ts.passes_completed += 1
            if end[0] > 70:
                ts.final_third_passes += 1
            if a.xt_added > 0:
                st.xt_added += a.xt_added
                ts.xt += a.xt_added
            if a.difficulty >= 7:
                st.difficult_passes += 1
            if a.defenders_bypassed >= 3:
                st.line_breaks += 1
            self._last_pass_by_possession[e.get("possession") or -1] = e
            if (a.defenders_bypassed >= 3 and a.difficulty >= 7.5 and (a.xt_added > 0.04 or a.defenders_bypassed >= 6)
                    and e["clock"] - self._last_line_breaker[team] > 300):
                self._last_line_breaker[team] = e["clock"]
                lane = ("threaded past a defender standing in the lane" if a.lane_clearance_m < 0.6 else
                        f"through a gap only {a.lane_clearance_m:.1f} m wide" if a.lane_clearance_m < 3 else
                        f"a {a.length_m:.0f} m pass")
                why = [f"bypassed {a.defenders_bypassed} defenders", f"difficulty {a.difficulty}/10 "
                       f"(only {a.completion_prob:.0%} of passes like this are completed)", lane]
                self._moment("line_breaking_pass", e, team, [pid] + ([e["receiver_id"]] if e.get("receiver_id") else []),
                             {"difficulty": a.difficulty, "completion_prob": round(a.completion_prob, 3),
                              "defenders_bypassed": a.defenders_bypassed, "length_m": round(a.length_m, 1),
                              "xt_added": round(float(a.xt_added), 3), "placement": a.accuracy,
                              "ball_speed_kmh": e["qualifiers"].get("speed_kmh"),
                              "start": [e["x"], e["y"]], "end": [e["end_x"], e["end_y"]]},
                             why, [e["event_id"]], update, tags=["passing"])
        self.window.append(_Window(e["clock"], "pass", team, e["outcome"], start[0], a.length_m,
                                   max(0.0, a.xt_added) if complete else 0.0, e.get("possession")))

    def _on_shot(self, e: dict, update: Update) -> None:
        team, pid = e["team_id"], e["player_id"]
        st, ts = self.ps(pid), self.teams[team]
        q = e["qualifiers"]
        d = e["attack_dir"]
        x, y = to_team_frame(e["x"], e["y"], d)
        frame = self.frame_at(e["t"])
        opp = to_team_frame_arr(self.positions(frame, self.other(team)), d) if frame else None
        xg, factors = shot_xg(x, y, opp, header=q.get("body_part") == "head", situation=q.get("situation", "open_play"))
        dur = max(0.05, self.clock - e["clock"])
        travel = math.hypot(e["end_x"] - e["x"], e["end_y"] - e["y"])
        tracked_speed = travel / dur * 3.6 if self.frames and dur > 0.05 else None
        speed = tracked_speed if tracked_speed and 30 < tracked_speed < 140 else q.get("speed_kmh", 0.0)
        e["_assessment"] = {"xg": round(xg, 3), "shot_speed_kmh": round(speed, 1), **factors}
        st.shots += 1
        st.xg += xg
        st.top_shot_speed_kmh = max(st.top_shot_speed_kmh, speed)
        st.touches += 1
        ts.shots += 1
        ts.xg += xg
        on_target = e["outcome"] in ("goal", "saved")
        ts.shots_on_target += on_target
        if xg >= 0.25:
            ts.big_chances += 1
        key = self._last_pass_by_possession.get(e.get("possession") or -1)
        if key and key["player_id"] != pid and key["team_id"] == team:
            kp = self.ps(key["player_id"])
            kp.key_passes += 1
            kp.xa += xg
        self._pending_shot = {"xg": xg, "speed": speed, "player_id": pid, "event_id": e["event_id"],
                              "factors": factors, "key_pass": key["event_id"] if key else None}
        self.window.append(_Window(e["clock"], "shot", team, e["outcome"], x, None, xg, e.get("possession")))
        outcome_text = {"saved": "Saved.", "off_target": "Off target.", "blocked": "Blocked.",
                        "post": "Off the post!", "goal": "Goal!"}.get(e["outcome"], "")
        why = [f"{factors['distance_m']:.0f} m out at a {factors['angle_deg']:.0f} degree angle"]
        if factors.get("nearest_defender_m") is not None:
            why.append(f"nearest defender {factors['nearest_defender_m']:.1f} m away")
        if e["outcome"] != "goal" and xg >= 0.25:
            self._moment("big_chance", e, team, [pid], {"xg": round(xg, 3), "distance_m": factors["distance_m"],
                         "outcome": e["outcome"], "outcome_text": outcome_text, "shot_speed_kmh": round(speed, 0)},
                         why, [e["event_id"]] + ([key["event_id"]] if key else []), update, tags=["chance"])
        elif e["outcome"] != "goal" and speed >= 108:
            self._moment("shot_speed", e, team, [pid], {"shot_speed_kmh": round(speed, 0), "xg": round(xg, 3)},
                         [f"{speed:.0f} km/h"], [e["event_id"]], update, tags=["speed"])

    def _on_goal(self, e: dict, update: Update) -> None:
        team, pid = e["team_id"], e["player_id"]
        was_behind = self.score[team] < self.score[self.other(team)]
        self.score[team] += 1
        self.teams[team].goals += 1
        st = self.ps(pid)
        st.goals += 1
        assist = e["qualifiers"].get("assist_id")
        if assist:
            self.ps(assist).assists += 1
        shot = self._pending_shot or {"xg": 0.1, "speed": 0, "factors": {}, "event_id": None, "key_pass": None}
        xg = shot["xg"]
        kind = "wonder_strike" if xg < 0.05 and e["qualifiers"].get("situation") != "penalty" else "goal"
        why = []
        f = shot["factors"]
        if f:
            why.append(f"{f.get('distance_m', 0):.0f} m out, xG {xg:.2f} (a goal from here happens about "
                       f"{max(1, round(xg * 100))} times in 100)")
        if was_behind and self.score[team] == self.score[self.other(team)]:
            why.append("an equaliser")
        elif self.score[team] == self.score[self.other(team)] + 1 and not was_behind:
            why.append("puts them ahead" if self.score[team] > 1 or self.score[self.other(team)] > 0 else "the opener")
        evidence = [x for x in (shot.get("event_id"), shot.get("key_pass"), e["event_id"]) if x]
        self._moment(kind, e, team, [pid] + ([assist] if assist else []),
                     {"xg": round(xg, 3), "distance_m": f.get("distance_m"), "shot_speed_kmh": round(shot["speed"], 0),
                      "assist_id": assist, "situation": e["qualifiers"].get("situation")},
                     why, evidence, update, tags=["goal"])
        # Milestones: brace / hat-trick, and season tallies when known.
        if st.goals in (2, 3):
            text = f"{self.full_names.get(pid, pid)} {'has a brace' if st.goals == 2 else 'completes a hat-trick'}!"
            self._moment("milestone", e, team, [pid], {"text": text, "goals_in_match": st.goals}, [text],
                         [e["event_id"]], update, tags=["milestone"])
        season_goals = self.season_players.get(pid, {}).get("goals")
        if season_goals is not None:
            total = season_goals + st.goals
            if total in (1, 5, 10, 15, 20) or total == season_goals + 1 and season_goals == 0:
                text = (f"First goal of the season for {self.full_names.get(pid, pid)}!" if total == 1 else
                        f"That's goal number {total} this season for {self.full_names.get(pid, pid)}.")
                self._moment("milestone", e, team, [pid], {"text": text, "season_goals": total}, [text],
                             [e["event_id"]], update, tags=["milestone", "season"])

    # ------------------------------------------------------------------ rolling tactics (every match minute)
    def _span(self, start: float, end: float) -> list[_Window]:
        return [w for w in self.window if start <= w.clock < end]

    def _on_minute(self, minute: int, update: Update) -> None:
        now = minute * 60.0
        recent = self._span(now - 300, now)
        threat = {self.home: 0.0, self.away: 0.0}
        for w in recent:
            if w.team in threat:
                threat[w.team] += w.threat * (1.5 if w.type == "shot" else 1.0)
        total = threat[self.home] + threat[self.away]
        share = threat[self.home] / total if total > 0 else 0.5
        value = round(2 * share - 1, 3)
        self.momentum.append({"minute": minute, "value": value, "home_threat": round(threat[self.home], 3),
                              "away_threat": round(threat[self.away], 3)})
        leader = self.home if value > 0.35 else self.away if value < -0.35 else None
        if leader and leader != self._momentum_leader and now - self._last_swing >= 300 and total > 0.12:
            self._last_swing = now
            lead_share = share if leader == self.home else 1 - share
            self._moment("momentum_swing", now, leader, [], {"threat_share": round(lead_share, 3),
                         "window_min": 5, "series_value": value},
                         [f"{lead_share:.0%} of the attacking threat in the last 5 minutes"], [], update,
                         tags=["momentum"])
        if leader:
            self._momentum_leader = leader
        if minute >= 6:
            self._control_regime(now, recent, update)
        if minute >= 20 and minute % 5 == 0:
            self._pressing_and_tempo(now, update)

    def _control_regime(self, now: float, recent: list[_Window], update: Update) -> None:
        passes = [w for w in recent if w.type == "pass"]
        if len(passes) < 20:
            return
        home_share = sum(1 for w in passes if w.team == self.home) / len(passes)
        possessions = {w.possession for w in recent if w.possession is not None}
        turnovers_pm = max(0, len(possessions) - 1) / 5.0
        duels_pm = sum(1 for w in recent if w.type in ("tackle", "take_on", "foul")) / 5.0
        long_share = sum(1 for w in passes if (w.length or 0) > 30) / len(passes)
        z = (turnovers_pm - 2.4) / 0.9 + (duels_pm - 1.0) / 0.8 + (long_share - 0.17) / 0.12
        chaos = 1 / (1 + math.exp(-z / 1.5))
        # Hysteresis: harder to enter a regime than to stay in it.
        cur = self.regime
        if chaos > (0.55 if cur == "chaos" else 0.68):
            regime = "chaos"
        elif home_share >= (0.57 if cur == "home_control" else 0.63):
            regime = "home_control"
        elif home_share <= (0.43 if cur == "away_control" else 0.37):
            regime = "away_control"
        else:
            regime = "balanced"
        cand, n = self._regime_candidate
        self._regime_candidate = (regime, n + 1 if cand == regime else 1)
        persisted = self._regime_candidate[1] >= 3  # three consecutive minute checks
        if regime != cur and persisted and now - self.regime_since >= 480:
            text = {
                "chaos": "It's become chaotic: end-to-end, lots of turnovers and duels.",
                "home_control": f"{self.names[self.home]} have taken control of the ball.",
                "away_control": f"{self.names[self.away]} have taken control of the ball.",
                "balanced": "Control is contested again; neither side dominates.",
            }[regime]
            team = self.home if regime == "home_control" else self.away if regime == "away_control" else None
            self._moment("control_shift", now, team, [],
                         {"regime": regime, "regime_text": text, "chaos": round(chaos, 2),
                          "possession_home": round(home_share, 3), "turnovers_per_min": round(turnovers_pm, 2),
                          "duels_per_min": round(duels_pm, 2), "long_ball_share": round(long_share, 2),
                          "previous": cur},
                         [f"{turnovers_pm:.1f} turnovers and {duels_pm:.1f} duels per minute",
                          f"pass share {home_share:.0%}-{1 - home_share:.0%}"], [], update, tags=["control"])
            self.regime, self.regime_since = regime, now

    def _ppda(self, team: str, start: float, end: float) -> tuple[float, int]:
        span = self._span(start, end)
        opp = self.other(team)
        opp_passes = sum(1 for w in span if w.type == "pass" and w.team == opp and (w.x_tf or 0) < 63)
        actions = sum(1 for w in span if w.team == team and w.type in ("tackle", "interception", "foul")
                      and (w.x_tf or 0) > 42)
        return opp_passes / max(1, actions), opp_passes

    def _pressing_and_tempo(self, now: float, update: Update) -> None:
        for team in (self.home, self.away):
            ppda_now, n_now = self._ppda(team, now - 600, now)
            ppda_before, n_before = self._ppda(team, now - 1200, now - 600)
            if n_now >= 20 and n_before >= 20 and now - self._last_shift[(team, "press")] >= 900:
                change = (ppda_now - ppda_before) / max(1.0, ppda_before)
                if abs(change) > 0.6:
                    self._last_shift[(team, "press")] = now
                    direction = "up" if ppda_now < ppda_before else "down"  # lower PPDA = more pressing
                    self._moment("pressing_shift", now, team, [], {"ppda_now": round(ppda_now, 1),
                                 "ppda_before": round(ppda_before, 1), "direction": direction},
                                 [f"PPDA {ppda_before:.1f} -> {ppda_now:.1f}: opponent passes allowed per defensive action"],
                                 [], update, tags=["tactics"])
        def tempo(a: float, b: float) -> tuple[float, int]:
            n = sum(1 for w in self._span(a, b) if w.type == "pass")
            return n / ((b - a) / 60), n
        t_now, n1 = tempo(now - 300, now)
        t_before, n2 = tempo(now - 600, now - 300)
        if n1 >= 10 and n2 >= 10 and now - self._last_shift[("match", "tempo")] >= 900:
            change = (t_now - t_before) / max(1.0, t_before)
            if abs(change) > 0.35:
                self._last_shift[("match", "tempo")] = now
                self._moment("tempo_shift", now, None, [], {"tempo_now": round(t_now, 1), "tempo_before": round(t_before, 1),
                             "direction": "up" if change > 0 else "down"},
                             [f"{t_before:.1f} -> {t_now:.1f} passes per minute"], [], update, tags=["rhythm"])

    # ------------------------------------------------------------------ outputs
    def impact(self) -> dict[str, float]:
        return {pid: st.impact for pid, st in self.players.items()}

    def snapshot(self, players: bool = True) -> dict:
        home_poss = self.teams[self.home].possession_s
        away_poss = self.teams[self.away].possession_s
        poss_total = home_poss + away_poss
        teams = {t: s.to_dict() for t, s in self.teams.items()}
        if poss_total > 0:
            teams[self.home]["possession"] = round(home_poss / poss_total, 3)
            teams[self.away]["possession"] = round(away_poss / poss_total, 3)
        snap = {
            "match_id": self.match_id,
            "home": self.home, "away": self.away,
            "home_name": self.names[self.home], "away_name": self.names[self.away],
            "clock": round(self.clock, 1), "minute": int(self.clock // 60) + 1, "period": self.period,
            "score": dict(self.score), "finished": self.finished,
            "teams": teams,
            "momentum": self.momentum[-30:],
            "regime": self.regime,
            "moments": len(self.moments),
        }
        if players:
            snap["players"] = {pid: st.to_dict() for pid, st in self.players.items()}
            snap["fantasy"] = self.fantasy.totals(self.impact(), finished=self.finished)
        return snap

    def field_tilt(self) -> dict[str, float]:
        h, a = self.teams[self.home].final_third_passes, self.teams[self.away].final_third_passes
        tot = h + a
        return {self.home: round(h / tot, 3) if tot else 0.5, self.away: round(a / tot, 3) if tot else 0.5}


def shot_distance(e: dict) -> float:
    x, y = to_team_frame(e["x"], e["y"], e["attack_dir"])
    return distance_to_goal(x, y)
