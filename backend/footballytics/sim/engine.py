"""MatchForge: an agent-based football match simulator producing events + 10 Hz tracking.

How it works
------------
* 22 player agents move continuously (acceleration-limited) towards targets derived from
  formation anchors, ball position, team phase (in / out of possession), pressing, marking
  and attacking runs. That yields physically plausible tracking data.
* The ball carrier chooses among options (passes to each teammate, through balls, carry,
  take-on, cross, shot, clearance) with a softmax over expected value. Values come from
  the same transparent xT / xG models the stats engine uses, scaled by player attributes
  and the club's tactical style. That keeps events consistent with positions.
* Outcomes of passes and shots are resolved at release and *choreographed*: the eventual
  receiver / interceptor runs to the arrival point, so the event log and tracking agree.
* Events are published when their outcome is known (a pass on arrival), like real feeds.
* Game state matters: trailing teams push up and go direct late on, fatigue lowers top
  speed, substitutions refresh legs, cards and penalties happen at realistic rates.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np

from ..league import FORMATION_ANCHORS, League, Player, pick_lineup
from ..models import expected_goals, expected_threat
from ..pitch import (
    BOX_DEPTH,
    BOX_Y_HIGH,
    BOX_Y_LOW,
    GOAL_Y_HIGH,
    GOAL_Y_LOW,
    PITCH_LENGTH,
    PITCH_WIDTH,
    distance_to_goal,
    in_box,
    point_segment_distance,
)
from ..schema import EventType as ET

DT = 0.1
PERIOD_SECONDS = 45 * 60
L, W = PITCH_LENGTH, PITCH_WIDTH


def _sig(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


@dataclass
class Flight:
    kind: str  # pass / cross / shot / clearance
    start: np.ndarray
    end: np.ndarray
    t0: float
    t1: float
    peak_z: float
    team: int
    passer: int
    receiver: int | None  # slot that will control the ball, None = out of play / goal
    resolution: str  # complete / intercepted / loose / out / goal / saved / blocked / off_target ...
    event: dict
    data: dict = field(default_factory=dict)


@dataclass
class Restart:
    kind: str  # kick_off / throw_in / goal_kick / corner / free_kick / penalty
    team: int
    spot: np.ndarray
    ready_t: float


@dataclass
class TeamState:
    club_id: str
    tactics: dict[str, float]
    formation: str
    subs_left: list[Player]
    subs_made: int = 0
    sub_times: list[float] = field(default_factory=list)


class MatchSim:
    """Simulates one match. Iterate :meth:`run` to get ``(frame, events)`` every 0.1 s."""

    def __init__(self, league: League, home_id: str, away_id: str, match_id: str, seed: int = 0):
        self.league = league
        self.match_id = match_id
        self.seed = seed
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)
        self.clubs = (league.clubs[home_id], league.clubs[away_id])

        self.slot_player: list[Player] = []
        anchors = []
        self.teams: list[TeamState] = []
        for club in self.clubs:
            starters, subs = pick_lineup(club)
            self.slot_player.extend(starters)
            anchors.extend(FORMATION_ANCHORS[club.formation])
            n_subs = self.rng.choice([3, 4, 4, 5, 5])
            times = sorted(self.rng.uniform(55, 88) * 60 for _ in range(n_subs))
            self.teams.append(TeamState(club.id, dict(club.tactics), club.formation, list(subs), 0, times))
        self.lineups = ([p.id for p in self.slot_player[:11]], [p.id for p in self.slot_player[11:]])
        self.slot_team = np.array([0] * 11 + [1] * 11)
        self.anchor = np.array(anchors, dtype=float)
        self.active = np.ones(22, dtype=bool)
        self._load_attributes()

        self.pos = np.zeros((22, 2))
        self.vel = np.zeros((22, 2))
        self.wobble = np.zeros((22, 2))
        self.dist_covered = np.zeros(22)
        self.fatigue = np.zeros(22)
        self.on_since = np.zeros(22)
        self.stunned_until = np.zeros(22)
        self.run_until = np.zeros(22)
        self.yellow: dict[str, int] = {}

        self.t = 0.0
        self.period = 1
        self.period_t = 0.0
        self.frame_no = 0
        self.stoppage = [self.rng.choice([1, 1, 2, 2, 3, 4]) * 60.0, self.rng.choice([3, 4, 4, 5, 6, 7, 8]) * 60.0]
        self.score = [0, 0]
        self.seq = 0
        self.possession_id = 0
        self.poss_team: int | None = None
        self.first_kickoff_team = self.rng.randint(0, 1)

        self.ball = np.array([L / 2, W / 2, 0.0])
        self.owner: int | None = None
        self.flight: Flight | None = None
        self.restart: Restart | None = None
        self.next_decision_t = 0.0
        self.carry_target: np.ndarray | None = None
        self.carry_from: tuple[np.ndarray, float] | None = None
        self.pressed_by: set[int] = set()
        self.last_touch_team = 0
        self.pending: list[dict] = []
        self.finished = False
        self.last_cross_receiver: int | None = None
        self.pass_chain: list[int] = []  # passers in current possession, for assists
        self.last_scorer_assist: tuple[int, int | None] | None = None

    # ------------------------------------------------------------------ setup helpers
    def _load_attributes(self) -> None:
        def arr(name: str) -> np.ndarray:
            return np.array([getattr(p, name) for p in self.slot_player], dtype=float)

        self.pace, self.passing, self.shooting = arr("pace"), arr("passing"), arr("shooting")
        self.dribbling, self.defending, self.vision = arr("dribbling"), arr("defending"), arr("vision")
        self.gk, self.stamina, self.composure = arr("goalkeeping"), arr("stamina"), arr("composure")
        self.is_gk = np.array([p.role == "GK" for p in self.slot_player])
        self.is_attacker = np.array([p.role in ("ST", "W", "AM") for p in self.slot_player])

    def direction(self, team: int) -> int:
        """+1 when ``team`` attacks towards x = 105 in the current period."""
        return 1 if (team == 0) == (self.period == 1) else -1

    def tf(self, xy: np.ndarray, team: int) -> np.ndarray:
        """Absolute -> team frame (also works in reverse, the transform is its own inverse)."""
        if self.direction(team) == 1:
            return xy.copy()
        out = np.array(xy, dtype=float, copy=True)
        out[..., 0] = L - out[..., 0]
        out[..., 1] = W - out[..., 1]
        return out

    def vtf(self, v: np.ndarray, team: int) -> np.ndarray:
        """Absolute velocity -> team-frame velocity."""
        return v.copy() if self.direction(team) == 1 else -v

    def team_slots(self, team: int) -> np.ndarray:
        idx = np.arange(11) + 11 * team
        return idx[self.active[idx]]

    def clock(self) -> float:
        return (self.period - 1) * PERIOD_SECONDS + self.period_t

    # ------------------------------------------------------------------ events
    def emit(self, etype: ET, team: int | None = None, slot: int | None = None, xy=None, end=None,
             outcome: str | None = None, receiver: int | None = None, t: float | None = None,
             under_pressure: bool = False, **qualifiers) -> dict:
        self.seq += 1
        ev = {
            "event_id": f"{self.match_id}-{self.seq:05d}",
            "match_id": self.match_id,
            "seq": self.seq,
            "t": round(self.t if t is None else t, 2),
            "period": self.period,
            "clock": round(self.clock() if t is None else self.clock() - (self.t - t), 2),
            "type": etype.value,
            "team_id": self.clubs[team].id if team is not None else None,
            "player_id": self.slot_player[slot].id if slot is not None else None,
            "x": round(float(xy[0]), 1) if xy is not None else None,
            "y": round(float(xy[1]), 1) if xy is not None else None,
            "end_x": round(float(end[0]), 1) if end is not None else None,
            "end_y": round(float(end[1]), 1) if end is not None else None,
            "outcome": outcome,
            "receiver_id": self.slot_player[receiver].id if receiver is not None else None,
            "possession": self.possession_id,
            "attack_dir": self.direction(team) if team is not None else None,
            "under_pressure": under_pressure,
            "qualifiers": qualifiers,
        }
        self.pending.append(ev)
        return ev

    # ------------------------------------------------------------------ possession helpers
    def give_ball(self, slot: int, reason: str | None = None) -> None:
        team = int(self.slot_team[slot])
        if self.poss_team != team:
            self.possession_id += 1
            self.poss_team = team
            self.pass_chain = []
            if reason == "recovery":
                self.emit(ET.BALL_RECOVERY, team, slot, self.pos[slot])
        self.owner = slot
        self.last_touch_team = team
        self.flight = None
        self.ball[:2] = self.pos[slot]
        self.ball[2] = 0.0
        tempo = self.teams[team].tactics["tempo"]
        self.next_decision_t = self.t + 1.25 + 1.9 * (1 - tempo) * self.rng.random() + 0.8 * self.rng.random()
        self.carry_target = None
        self.carry_from = (self.pos[slot].copy(), self.t)
        self.pressed_by = set()

    def nearest(self, xy: np.ndarray, team: int, exclude_gk: bool = False) -> int:
        slots = self.team_slots(team)
        if exclude_gk:
            slots = slots[~self.is_gk[slots]]
        d = np.linalg.norm(self.pos[slots] - xy, axis=1)
        return int(slots[int(np.argmin(d))])

    def pressure_on(self, slot: int) -> tuple[float, int | None, float]:
        """(pressure 0..1, nearest opponent slot, distance)."""
        opp = self.team_slots(1 - int(self.slot_team[slot]))
        d = np.linalg.norm(self.pos[opp] - self.pos[slot], axis=1)
        i = int(np.argmin(d))
        dist = float(d[i])
        return max(0.0, min(1.0, (4.0 - dist) / 3.2)), int(opp[i]), dist

    def offside_line(self, team: int) -> float:
        """Offside line for ``team`` (attacking) in its own team frame."""
        opp = self.team_slots(1 - team)
        xs = np.sort(self.tf(self.pos[opp], team)[:, 0])[::-1]
        second_last = xs[1] if len(xs) > 1 else xs[0]
        ball_x = self.tf(self.ball[:2], team)[0]
        return float(max(second_last, ball_x, L / 2))

    # ------------------------------------------------------------------ main loop
    def run(self) -> Iterator[tuple[dict, list[dict]]]:
        self._start_period(kickoff_team=self.first_kickoff_team)
        while not self.finished:
            self.step()
            frame = self.frame()
            events, self.pending = self.pending, []
            yield frame, events

    def _start_period(self, kickoff_team: int) -> None:
        if self.period == 1:
            self.emit(ET.MATCH_START, outcome=None, home=self.clubs[0].id, away=self.clubs[1].id)
        self.emit(ET.PERIOD_START, home_attack_dir=self.direction(0))
        for slot in range(22):
            if not self.active[slot]:
                continue
            team = int(self.slot_team[slot])
            depth, width = self.anchor[slot]
            tx = 1.5 + depth * 46 if not self.is_gk[slot] else 4.0
            tx = min(tx, L / 2 - 1.0)
            self.pos[slot] = self.tf(np.array([tx, width * W]), team)
            self.vel[slot] = 0
        self.ball[:] = (L / 2, W / 2, 0)
        self.restart = Restart("kick_off", kickoff_team, np.array([L / 2, W / 2]), self.t + 0.5)
        self.owner = None
        self.flight = None

    def step(self) -> None:
        self.t += DT
        self.period_t += DT
        self.frame_no += 1
        if self.restart is not None:
            self._handle_restart()
        elif self.flight is not None:
            self._advance_flight()
        elif self.owner is not None:
            self._on_ball()
        self._move_players()
        self._check_period_end()

    # ------------------------------------------------------------------ period / subs
    def _check_period_end(self) -> None:
        if self.period_t < PERIOD_SECONDS + self.stoppage[self.period - 1] or self.flight is not None:
            return
        if self.owner is not None:
            # Don't blow the whistle in the middle of an attack.
            owner_x = self.tf(self.pos[self.owner], int(self.slot_team[self.owner]))[0]
            if owner_x > 75 and self.period_t < PERIOD_SECONDS + self.stoppage[self.period - 1] + 30:
                return
        self._flush_carry()
        self.emit(ET.PERIOD_END, home_score=self.score[0], away_score=self.score[1])
        if self.period == 1:
            self.period = 2
            self.period_t = 0.0
            self._start_period(kickoff_team=1 - self.first_kickoff_team)
        else:
            self.emit(ET.MATCH_END, home_score=self.score[0], away_score=self.score[1])
            self.finished = True

    def _maybe_substitute(self) -> None:
        for team, ts in enumerate(self.teams):
            while ts.sub_times and self.clock() >= ts.sub_times[0] and ts.subs_left:
                ts.sub_times.pop(0)
                slots = [s for s in self.team_slots(team) if not self.is_gk[s]]
                if not slots:
                    return
                # Bring off the most tired outfielder (fatigue ~ distance relative to stamina).
                tired = max(slots, key=lambda s: self.dist_covered[s] / (60 + self.stamina[s]))
                group = self.slot_player[tired].group
                incoming = next((p for p in ts.subs_left if p.group == group), None)
                incoming = incoming or next((p for p in ts.subs_left if p.role != "GK"), None)
                if incoming is None:
                    return
                ts.subs_left.remove(incoming)
                outgoing = self.slot_player[tired]
                self.emit(ET.SUBSTITUTION, team, tired, self.pos[tired], replacement_id=incoming.id,
                          replacement_name=incoming.name, player_off_name=outgoing.name)
                self.slot_player[tired] = incoming
                self._load_attributes()
                self.dist_covered[tired] = 0.0
                self.on_since[tired] = self.t
                ts.subs_made += 1
                if self.restart is not None:
                    self.restart.ready_t += self.rng.uniform(18, 30)  # substitutions stop the game

    # ------------------------------------------------------------------ restarts
    def _award(self, kind: str, team: int, spot: np.ndarray, delay: tuple[float, float]) -> None:
        self._flush_carry()
        self.owner = None
        self.flight = None
        spot = spot.copy()
        spot[0] = min(max(spot[0], 0.0), L)
        spot[1] = min(max(spot[1], 0.0), W)
        self.restart = Restart(kind, team, spot, self.t + self.rng.uniform(*delay))
        self.ball[:2] = spot
        self.ball[2] = 0.0
        if kind in ("corner", "throw_in", "goal_kick", "free_kick"):
            self.emit({"corner": ET.CORNER, "throw_in": ET.THROW_IN, "goal_kick": ET.GOAL_KICK,
                       "free_kick": ET.FREE_KICK}[kind], team, None, spot)

    def _ball_out(self, last_team: int, where: np.ndarray, touch_slot: int | None) -> None:
        """Ball crossed a line; ``where`` is the absolute exit point."""
        self.emit(ET.BALL_OUT, last_team, touch_slot, where)
        other = 1 - last_team
        x, y = float(where[0]), float(where[1])
        if 0.5 < x < L - 0.5:
            spot = np.array([x, 0.0 if y < W / 2 else W])
            self._award("throw_in", other, spot, (11, 24))
            return
        # Over a goal line. Whose goal line?
        defending = other
        if self.tf(np.array([x, y]), last_team)[0] > L / 2:
            # Last touch by the attacking team over the opponent's line -> goal kick for defenders.
            gk_spot = self.tf(np.array([5.5, W / 2 + self.rng.choice([-9.0, 9.0])]), defending)
            self._award("goal_kick", defending, gk_spot, (22, 38))
        else:
            # Defender put it behind their own line -> corner for the attackers.
            corner_y = 0.0 if y < W / 2 else W
            self._award("corner", other, np.array([0.0 if x < L / 2 else L, corner_y]), (30, 48))

    def _handle_restart(self) -> None:
        r = self.restart
        assert r is not None
        if r.kind != "kick_off":
            self._maybe_substitute()
        if self.t < r.ready_t:
            return
        team = r.team
        keepers = [s for s in self.team_slots(team) if self.is_gk[s]]
        if r.kind == "kick_off":
            slot = self.nearest(r.spot, team, exclude_gk=True)
        elif r.kind == "goal_kick" and keepers:
            slot = int(keepers[0])
        else:
            slot = self.nearest(r.spot, team, exclude_gk=r.kind != "free_kick")
        self.pos[slot] = r.spot
        self.vel[slot] = 0
        kind = r.kind
        self.restart = None
        self.give_ball(slot)
        self.carry_from = None
        if kind == "penalty":
            self._shoot(slot, situation="penalty")
        elif kind == "corner":
            self._cross(slot, set_piece="corner")
        elif kind == "free_kick":
            p = self.tf(self.pos[slot], team)
            xg = expected_goals(p[0], p[1], situation="direct_free_kick").xg
            if distance_to_goal(p[0], p[1]) < 30 and xg > 0.035 and self.rng.random() < 0.6:
                self._shoot(slot, situation="direct_free_kick")
            elif p[0] > 75 and self.rng.random() < 0.7:
                self._cross(slot, set_piece="free_kick")
            else:
                self._pass(slot, set_piece="free_kick")
        elif kind == "throw_in":
            self._pass(slot, set_piece="throw_in", max_len=22)
        elif kind == "goal_kick":
            go_long = self.rng.random() < 0.3 + 0.6 * self.teams[team].tactics["directness"]
            self._pass(slot, set_piece="goal_kick", long_bias=1.6 if go_long else 0.0)
        else:  # kick off
            self._pass(slot, set_piece="kick_off", max_len=20, backwards=True)

    # ------------------------------------------------------------------ on-ball decisions
    def _flush_carry(self) -> None:
        if self.owner is None or self.carry_from is None:
            self.carry_from = None
            return
        start, t0 = self.carry_from
        end = self.pos[self.owner]
        if np.linalg.norm(end - start) >= 3.0:
            team = int(self.slot_team[self.owner])
            self.emit(ET.CARRY, team, self.owner, start, end, t=t0, duration=round(self.t - t0, 1),
                      distance_m=round(float(np.linalg.norm(end - start)), 1))
        self.carry_from = None

    def _on_ball(self) -> None:
        slot = self.owner
        assert slot is not None
        team = int(self.slot_team[slot])
        pressure, presser, pdist = self.pressure_on(slot)

        # Pressure events (once per presser per spell on the ball).
        if pdist < 3.0 and presser not in self.pressed_by:
            self.pressed_by.add(presser)
            self.emit(ET.PRESSURE, 1 - team, presser, self.pos[presser], target_id=self.slot_player[slot].id)

        # Tackle attempts by a close, goal-side defender.
        if pdist < 1.7 and self.t > self.stunned_until[presser]:
            goal_side = self.tf(self.pos[presser], team)[0] > self.tf(self.pos[slot], team)[0] - 0.5
            rate = 0.11 * (self.defending[presser] / 75.0) * (0.7 + 0.6 * self.teams[1 - team].tactics["press"])
            if goal_side and self.rng.random() < rate * DT:
                self._tackle(presser, slot)
                return

        if self.t < self.next_decision_t:
            # A goal-side defender in the carrier's path blocks the carry: decide now (take on or pass).
            if pdist < 1.5 and self.carry_target is not None:
                ahead = self.tf(self.pos[presser], team)[0] > self.tf(self.pos[slot], team)[0]
                if ahead:
                    self.carry_target = None
                    self.next_decision_t = self.t
            return
        self._decide(slot, pressure)

    def _decide(self, slot: int, pressure: float) -> None:
        team = int(self.slot_team[slot])
        tac = self.teams[team].tactics
        me = self.tf(self.pos[slot], team)
        mates = np.array([s for s in self.team_slots(team) if s != slot])
        opps = self.team_slots(1 - team)
        mates_tf = self.tf(self.pos[mates], team)
        opps_tf = self.tf(self.pos[opps], team)
        late_push = self._game_state_push(team)

        options: list[tuple[float, str, object]] = []
        here_xt = expected_threat(me[0], me[1])
        turnover_cost = expected_threat(L - me[0], W - me[1]) * 0.9

        # --- passes (with a small lead in the receiver's running direction)
        targets = mates_tf + self.vtf(self.vel[mates], team) * 0.5
        targets[:, 0] = np.clip(targets[:, 0], 1, L - 1)
        targets[:, 1] = np.clip(targets[:, 1], 1, W - 1)
        offside = self.offside_line(team)
        for i, s in enumerate(mates):
            tgt = targets[i]
            length = float(np.linalg.norm(tgt - me))
            if length < 4:
                continue
            p, lane_d = self._pass_success(slot, me, tgt, opps_tf, pressure)
            if tgt[0] > offside + 0.5 and tgt[0] > me[0]:
                p *= 0.15  # receiver standing offside: very unlikely to be a sensible pass
            value = expected_threat(tgt[0], tgt[1])
            lost_at = me + 0.75 * (tgt - me)  # a failed pass is usually lost near its target
            loss = expected_threat(L - lost_at[0], W - lost_at[1]) * 0.9
            u = p * value - (1 - p) * loss
            if self.is_gk[s]:
                u -= 0.004
            if length > 28:
                u += 0.006 * (tac["directness"] + late_push - 0.35)
            elif length < 18:
                u += 0.004 * (0.7 - tac["directness"])
            options.append((u, "pass", (s, tgt, p)))

        # --- through balls to runners
        for s in mates[self.run_until[mates] > self.t]:
            if self.tf(self.pos[s], team)[0] > offside + 1.0:
                continue  # passer can see the runner is already offside
            tgt = self.tf(self.pos[s], team) + self.vtf(self.vel[s], team) * 1.3 + np.array([2.5, 0.0])
            tgt[0] = min(tgt[0], L - 3)
            if tgt[0] <= me[0] + 5:
                continue
            p, _ = self._pass_success(slot, me, tgt, opps_tf, pressure, through=True)
            value = expected_threat(tgt[0], tgt[1]) * 1.15
            loss = expected_threat(L - tgt[0], W - tgt[1]) * 0.9
            options.append((p * value - (1 - p) * loss + 0.004, "through", (s, tgt, p)))

        # --- shot
        dist = distance_to_goal(me[0], me[1])
        if dist < 32 and me[0] > L / 2:
            xg = expected_goals(me[0], me[1], pressure=pressure).xg
            appetite = 0.85 + 0.6 * self.shooting[slot] / 100 + 0.35 * late_push
            u = xg * appetite * 0.88 + (0.019 if 16 < dist < 30 and pressure < 0.7 else 0.0)
            if xg > 0.012:
                options.append((u, "shot", None))

        # --- cross from wide areas in the final third
        if me[0] > 72 and (me[1] < BOX_Y_LOW + 4 or me[1] > BOX_Y_HIGH - 4):
            in_box_mates = sum(1 for m in mates_tf if m[0] > L - 20 and BOX_Y_LOW - 2 < m[1] < BOX_Y_HIGH + 2)
            if in_box_mates:
                u = (0.022 + 0.03 * tac["crossing"]) * min(3, in_box_mates)
                options.append((u, "cross", None))

        # --- carry / take-on
        ahead = me + np.array([7.0, 0.0])
        ahead[1] += np.clip((W / 2 - me[1]) * 0.15, -3, 3)
        d_ahead = float(np.min(np.linalg.norm(opps_tf - ahead, axis=1)))
        space = min(1.0, d_ahead / 7.0)
        carry_v = expected_threat(min(ahead[0], L - 2), ahead[1])
        opp_d = np.linalg.norm(opps_tf - me, axis=1)
        blocker_in_front = bool(np.any((opps_tf[:, 0] > me[0]) & (opp_d < 2.6)))
        p_keep = 0.97 - 0.45 * pressure * (1 - self.dribbling[slot] / 140)
        if not blocker_in_front:  # with a defender in the way you must take him on (or pass)
            gain = here_xt + 0.6 * (carry_v - here_xt)
            u_carry = p_keep * gain * (0.75 + 0.25 * space) - (1 - p_keep) * turnover_cost + 0.0015 * space
            options.append((u_carry, "carry", ahead))
        elif me[0] > 25:
            p_beat = _sig((self.dribbling[slot] - 78) / 25.0)
            options.append((p_beat * carry_v * 1.1 - (1 - p_beat) * turnover_cost - 0.006, "take_on", ahead))

        # --- clearance under pressure deep in own half
        if me[0] < 22 and pressure > 0.5 and not self.is_gk[slot]:
            options.append((turnover_cost * 0.6 + 0.004, "clearance", None))

        if not options:
            options.append((0.0, "carry", ahead))

        temp = 0.0025 + 0.0045 * (1.0 - self.vision[slot] / 100.0)
        us = np.array([o[0] for o in options])
        probs = np.exp((us - us.max()) / temp)
        probs /= probs.sum()
        kind, payload = options[int(self.np_rng.choice(len(options), p=probs))][1:]

        if kind in ("pass", "through"):
            s, tgt, p = payload  # type: ignore[misc]
            self._pass(slot, receiver=int(s), target_tf=tgt, p_success=p, through=kind == "through")
        elif kind == "shot":
            self._shoot(slot, pressure=pressure)
        elif kind == "cross":
            self._cross(slot)
        elif kind == "clearance":
            self._clear(slot)
        elif kind == "take_on":
            self._take_on(slot)
        else:
            self.carry_target = self.tf(np.asarray(payload), team)
            self.next_decision_t = self.t + self.rng.uniform(0.8, 1.8)

    def _pass_success(self, slot: int, me: np.ndarray, tgt: np.ndarray, opps_tf: np.ndarray, pressure: float,
                      through: bool = False) -> tuple[float, float]:
        length = float(np.linalg.norm(tgt - me))
        lane, tpar = point_segment_distance(opps_tf, me, tgt)
        lane = np.where(tpar > 0.08, lane, 99.0)
        lane_d = float(lane.min())
        to_target = np.linalg.norm(opps_tf - tgt, axis=1)
        recv_d = float(to_target.min())
        crowd = int(np.sum(to_target < 4.5))
        skill = (self.passing[slot] - 70) / 30
        z = (3.45 + 0.9 * skill - 0.042 * length - 2.4 * math.exp(-lane_d / 1.5) - 1.0 * math.exp(-recv_d / 2.2)
             - 0.8 * pressure - 0.35 * max(0, crowd - 1))
        if through:
            z -= 1.3
        if tgt[0] > 70:
            z -= 0.55 + 0.02 * (tgt[0] - 70)  # final-third passes are far more contested
        if in_box(tgt[0], tgt[1]):
            z -= 1.6  # defenders prioritise the box; receptions there are contested
        fatigue = self._fatigue(slot)
        z -= 0.6 * fatigue
        return _sig(z), lane_d

    def _fatigue(self, slot: int) -> float:
        played = self.dist_covered[slot] / 1000.0
        return max(0.0, min(0.6, (played - 6.0) / (14 + 6 * self.stamina[slot] / 100)))

    def _game_state_push(self, team: int) -> float:
        """0..1 urgency for a team chasing the game late on (negative-ish when protecting a lead)."""
        diff = self.score[team] - self.score[1 - team]
        minute = self.clock() / 60
        if diff < 0 and minute > 65:
            return min(1.0, (minute - 65) / 25) * (0.6 if diff == -1 else 0.8)
        if diff > 0 and minute > 75:
            return -0.3
        return 0.0

    # ------------------------------------------------------------------ actions
    def _pass(self, slot: int, receiver: int | None = None, target_tf: np.ndarray | None = None,
              p_success: float | None = None, set_piece: str | None = None, max_len: float = 999,
              long_bias: float = 0.0, backwards: bool = False, through: bool = False) -> None:
        team = int(self.slot_team[slot])
        me = self.tf(self.pos[slot], team)
        pressure, _, _ = self.pressure_on(slot)
        opps_tf = self.tf(self.pos[self.team_slots(1 - team)], team)
        if receiver is None:
            mates = [s for s in self.team_slots(team) if s != slot and not self.is_gk[s]]
            mates_tf = self.tf(self.pos[mates], team)
            d = np.linalg.norm(mates_tf - me, axis=1)
            score = []
            for i, s in enumerate(mates):
                if d[i] > max_len or (backwards and mates_tf[i][0] > me[0] + 1):
                    score.append(-1e9)
                    continue
                p, _ = self._pass_success(slot, me, mates_tf[i], opps_tf, pressure)
                gain = expected_threat(mates_tf[i][0], mates_tf[i][1])
                score.append(math.log(p + 1e-6) + 40 * gain + long_bias * 0.06 * d[i] + self.rng.gauss(0, 0.4))
            k = int(np.argmax(score))
            receiver, target_tf = int(mates[k]), mates_tf[k]
            p_success, _ = self._pass_success(slot, me, target_tf, opps_tf, pressure)
        assert target_tf is not None and p_success is not None
        if set_piece in ("throw_in", "kick_off"):
            p_success = min(0.97, p_success + 0.15)
        self._flush_carry()
        self.pass_chain.append(slot)
        length = float(np.linalg.norm(target_tf - me))
        lofted = length > 30 or set_piece == "goal_kick" and length > 25
        # Offside: receiver beyond the second-last defender when the ball is played (marginal calls are a coin flip).
        margin = self.tf(self.pos[receiver], team)[0] - self.offside_line(team)
        offside = set_piece not in ("throw_in", "goal_kick", "corner") and (
            margin > 1.2 or (margin > -0.3 and through and self.rng.random() < 0.35))

        success = self.rng.random() < p_success
        end_tf = target_tf.copy()
        resolution = "complete"
        recv_slot: int | None = receiver
        if offside:
            resolution = "offside"
        elif not success:
            lane, tpar = point_segment_distance(opps_tf, me, target_tf)
            lane = np.where(tpar > 0.08, lane, 99.0)
            j = int(np.argmin(lane))
            opp_slots = self.team_slots(1 - team)
            if lane[j] < 3.5 and self.rng.random() < 0.75:
                # Cut out in the lane = interception; picked off at the receiver = ball recovery.
                resolution = "intercepted" if tpar[j] < 0.8 and self.rng.random() < 0.18 else "recovered"
                end_tf = me + (target_tf - me) * float(tpar[j])
                recv_slot = int(opp_slots[j])
            else:
                err = self.np_rng.normal(0, 4.5 + 0.18 * length, 2)
                end_tf = target_tf + err
                # Overhit / wayward passes often run out of play, especially near the touchlines.
                near_touch = min(target_tf[1], W - target_tf[1])
                if self.rng.random() < 0.1 + 0.3 * max(0.0, (14 - near_touch) / 14):
                    if target_tf[0] > L - 14 and self.rng.random() < 0.5:
                        end_tf = np.array([L + 1.0, target_tf[1] + self.rng.gauss(0, 4)])
                    else:
                        end_tf = np.array([target_tf[0] + self.rng.gauss(0, 4), -1.0 if target_tf[1] < W / 2 else W + 1])
                if not (0 < end_tf[0] < L and 0 < end_tf[1] < W):
                    resolution = "out"
                    recv_slot = None
                    end_tf = np.array([min(max(end_tf[0], -1.0), L + 1.0), min(max(end_tf[1], -1.0), W + 1.0)])
                else:
                    # Loose ball: whoever is closest (either team), weighted by distance.
                    abs_end = self.tf(end_tf, team)
                    cands = np.where(self.active)[0]
                    d = np.linalg.norm(self.pos[cands] - abs_end, axis=1) + self.np_rng.uniform(0, 3, len(cands))
                    recv_slot = int(cands[int(np.argmin(d))])
                    resolution = "recovered" if self.slot_team[recv_slot] != team else "loose_won"
        else:
            end_tf = target_tf + self.np_rng.normal(0, 0.4 + 0.02 * length, 2)
            end_tf[0] = np.clip(end_tf[0], 0.5, L - 0.5)
            end_tf[1] = np.clip(end_tf[1], 0.5, W - 0.5)

        travel = float(np.linalg.norm(end_tf - me))
        speed = (13.0 + 0.22 * travel) if lofted else min(24.0, 8.5 + 0.42 * travel)
        dur = max(0.25, travel / speed)
        start_abs = self.pos[slot].copy()
        end_abs = self.tf(end_tf, team)
        kind = "pass"
        ev = dict(type=ET.PASS, team=team, slot=slot, start=start_abs, end=end_abs, under_pressure=pressure > 0.4,
                  q=dict(length_m=round(length, 1), height="high" if lofted else "ground",
                         speed_kmh=round(speed * 3.6, 1), through_ball=through,
                         set_piece=set_piece, intended_receiver_id=self.slot_player[receiver].id,
                         pass_kind=("through" if through else "long" if length > 30 else "short" if length < 15
                                    else "medium")))
        self.flight = Flight(kind, start_abs, end_abs, self.t, self.t + dur, (6 + 0.12 * travel) if lofted else 0.0,
                             team, slot, recv_slot, resolution, ev)
        self.owner = None

    def _cross(self, slot: int, set_piece: str | None = None) -> None:
        team = int(self.slot_team[slot])
        me = self.tf(self.pos[slot], team)
        self._flush_carry()
        self.pass_chain.append(slot)
        attackers = [s for s in self.team_slots(team) if s != slot and not self.is_gk[s]]
        att_tf = self.tf(self.pos[attackers], team)
        box_targets = [(s, p) for s, p in zip(attackers, att_tf) if p[0] > L - 22 and BOX_Y_LOW - 4 < p[1] < BOX_Y_HIGH + 4]
        aim = np.array([L - self.rng.uniform(6, 13), W / 2 + self.rng.uniform(-7, 7)])
        if box_targets:
            s, p = self.rng.choice(box_targets)
            aim = np.array([max(p[0], L - 15), p[1]]) + self.np_rng.normal(0, 1.5, 2)
        defenders = self.team_slots(1 - team)
        def_tf = self.tf(self.pos[defenders], team)
        d_def = np.linalg.norm(def_tf - aim, axis=1)
        d_att = np.linalg.norm(att_tf - aim, axis=1) if len(attackers) else np.array([99.0])
        quality = (self.passing[slot] + self.vision[slot]) / 200
        p_att = _sig(-1.3 + 1.0 * (quality - 0.7) / 0.3 + 0.35 * (float(d_def.min()) - float(d_att.min())))
        if set_piece == "corner":
            p_att = min(0.45, p_att + 0.05)
        aim[0] = min(aim[0], L - 1)
        if self.rng.random() < p_att and len(attackers):
            recv = int(attackers[int(np.argmin(d_att))])
            resolution = "complete"
        else:
            recv = int(defenders[int(np.argmin(d_def))])
            resolution = "intercepted"
        start_abs, end_abs = self.pos[slot].copy(), self.tf(aim, team)
        length = float(np.linalg.norm(aim - me))
        speed = 17.0 + 0.15 * length
        ev = dict(type=ET.CROSS, team=team, slot=slot, start=start_abs, end=end_abs, under_pressure=False,
                  q=dict(length_m=round(length, 1), height="high", speed_kmh=round(speed * 3.6, 1),
                         set_piece=set_piece, pass_kind="cross"))
        self.flight = Flight("cross", start_abs, end_abs, self.t, self.t + length / speed, 5.5 + 0.1 * length,
                             team, slot, recv, resolution, ev, {"set_piece": set_piece})
        self.owner = None

    def _clear(self, slot: int) -> None:
        team = int(self.slot_team[slot])
        me = self.tf(self.pos[slot], team)
        self._flush_carry()
        aim = np.array([min(me[0] + self.rng.uniform(28, 50), L + 1), np.clip(me[1] + self.rng.gauss(0, 24), -1, W + 1)])
        start_abs = self.pos[slot].copy()
        if not 0 < aim[1] < W:
            end_abs = self.tf(aim, team)
            ev = dict(type=ET.CLEARANCE, team=team, slot=slot, start=start_abs, end=end_abs, under_pressure=True, q={})
            self.flight = Flight("clearance", start_abs, end_abs, self.t, self.t + 1.6, 12.0, team, slot, None, "out", ev)
        else:
            end_abs = self.tf(aim, team)
            cands = np.where(self.active)[0]
            d = np.linalg.norm(self.pos[cands] - end_abs, axis=1) + self.np_rng.uniform(0, 5, len(cands))
            recv = int(cands[int(np.argmin(d))])
            ev = dict(type=ET.CLEARANCE, team=team, slot=slot, start=start_abs, end=end_abs, under_pressure=True, q={})
            self.flight = Flight("clearance", start_abs, end_abs, self.t, self.t + 1.8, 14.0, team, slot, recv,
                                 "loose_won" if self.slot_team[recv] == team else "intercepted", ev)
        self.owner = None

    def _take_on(self, slot: int) -> None:
        team = int(self.slot_team[slot])
        _, opp, dist = self.pressure_on(slot)
        self._flush_carry()
        p = _sig((self.dribbling[slot] - self.defending[opp]) / 25.0 - 0.1 - 0.8 * self._fatigue(slot))
        won = self.rng.random() < p
        self.emit(ET.TAKE_ON, team, slot, self.pos[slot], outcome="success" if won else "fail",
                  defender_id=self.slot_player[opp].id)
        me_tf = self.tf(self.pos[slot], team)
        if won and self.rng.random() < (0.08 if in_box(me_tf[0], me_tf[1]) else 0.36):
            # Beaten defender pulls the attacker back: tactical foul.
            self.emit(ET.FOUL, 1 - team, opp, self.pos[opp], outcome="committed", fouled_id=self.slot_player[slot].id,
                      tactical=True)
            self._maybe_card(opp, me_tf, tactical=True)
            if in_box(me_tf[0], me_tf[1]):
                self._award_penalty(team, slot)
            else:
                self._award("free_kick", team, self.pos[slot], (26, 46))
            return
        if not won and self.rng.random() < 0.22:
            self.emit(ET.TACKLE, 1 - team, opp, self.pos[opp], outcome="won", opponent_id=self.slot_player[slot].id)
            self._knock_out(opp, self.pos[slot])
            return
        if won:
            self.stunned_until[opp] = self.t + 1.6
            me = self.tf(self.pos[slot], team)
            self.carry_target = self.tf(me + np.array([8.0, self.rng.uniform(-3, 3)]), team)
            self.carry_from = (self.pos[slot].copy(), self.t)
            self.next_decision_t = self.t + self.rng.uniform(0.6, 1.3)
        else:
            self.emit(ET.TACKLE, 1 - team, opp, self.pos[opp], outcome="won", opponent_id=self.slot_player[slot].id)
            self.give_ball(opp, reason="recovery")

    def _tackle(self, tackler: int, carrier: int) -> None:
        team = int(self.slot_team[carrier])
        carrier_tf = self.tf(self.pos[carrier], team)
        in_tacklers_box = in_box(carrier_tf[0], carrier_tf[1])
        foul_p = 0.33 + 0.25 * self._fatigue(tackler) - (0.2 if in_tacklers_box else 0.0)
        r = self.rng.random()
        self._flush_carry()
        if r < foul_p:
            self.emit(ET.FOUL, 1 - team, tackler, self.pos[tackler], outcome="committed",
                      fouled_id=self.slot_player[carrier].id)
            self._maybe_card(tackler, carrier_tf)
            if in_tacklers_box:
                self._award_penalty(team, carrier)
            else:
                self._award("free_kick", team, self.pos[carrier], (26, 46))
            return
        p_win = _sig((self.defending[tackler] - self.dribbling[carrier]) / 25.0 + 0.15)
        if self.rng.random() < p_win:
            self.emit(ET.TACKLE, 1 - team, tackler, self.pos[tackler], outcome="won",
                      opponent_id=self.slot_player[carrier].id)
            r2 = self.rng.random()
            if r2 < 0.55:
                self.give_ball(tackler, reason="recovery")
            elif r2 < 0.78:
                self._knock_out(tackler, self.pos[carrier])
            else:  # ball squirts loose to someone nearby
                cands = np.where(self.active)[0]
                d = np.linalg.norm(self.pos[cands] - self.pos[carrier], axis=1) + self.np_rng.uniform(0, 4, len(cands))
                d[cands == carrier] = 99
                self.give_ball(int(cands[int(np.argmin(d))]), reason="recovery")
        else:
            self.emit(ET.TACKLE, 1 - team, tackler, self.pos[tackler], outcome="lost",
                      opponent_id=self.slot_player[carrier].id)
            self.stunned_until[tackler] = self.t + 1.8
            self.carry_from = (self.pos[carrier].copy(), self.t)

    def _award_penalty(self, team: int, fouled: int) -> None:
        self.emit(ET.PENALTY_AWARDED, team, fouled, self.pos[fouled])
        spot = self.tf(np.array([L - 11.0, W / 2]), team)
        self.restart = Restart("penalty", team, spot, self.t + self.rng.uniform(60, 90))
        self.owner = None
        self.flight = None
        self.ball[:2] = spot

    def _knock_out(self, last_touch: int, where: np.ndarray) -> None:
        """A challenge sends the ball out of play near ``where`` (absolute)."""
        x, y = float(where[0]), float(where[1])
        team = int(self.slot_team[last_touch])
        if min(y, W - y) < 20 or self.rng.random() < 0.5:
            exit_pt = np.array([x, 0.0 if y < W / 2 else W])
        else:
            exit_pt = np.array([0.0 if x < L / 2 else L, y])
        self._ball_out(team, exit_pt, last_touch)

    def _maybe_card(self, slot: int, at_tf: np.ndarray, tactical: bool = False) -> None:
        pid = self.slot_player[slot].id
        team = int(self.slot_team[slot])
        r = self.rng.random()
        if r < 0.004 + (0.05 if at_tf[0] > L - 25 else 0.0) * 0.1:
            self._send_off(slot, "red")
        elif r < (0.45 if tactical else 0.14):
            self.yellow[pid] = self.yellow.get(pid, 0) + 1
            if self.yellow[pid] >= 2:
                self._send_off(slot, "second_yellow")
            else:
                self.emit(ET.CARD, team, slot, self.pos[slot], outcome="yellow")

    def _send_off(self, slot: int, kind: str) -> None:
        team = int(self.slot_team[slot])
        self.emit(ET.CARD, team, slot, self.pos[slot], outcome=kind)
        self.active[slot] = False
        self.pos[slot] = (L / 2, -5.0)

    def _shoot(self, slot: int, pressure: float = 0.0, situation: str = "open_play", header: bool = False) -> None:
        team = int(self.slot_team[slot])
        me = self.tf(self.pos[slot], team)
        self._flush_carry()
        brk = expected_goals(me[0], me[1], header=header, pressure=pressure, situation=situation)
        keeper = [s for s in self.team_slots(1 - team) if self.is_gk[s]]
        gk_skill = self.gk[keeper[0]] if keeper else 30.0
        finishing = 0.92 + 0.45 * (self.shooting[slot] - 60) / 40 - 0.4 * self._fatigue(slot)
        keeper_mod = 1.28 - 0.3 * gk_skill / 100
        p_goal = min(0.95, brk.xg * finishing * keeper_mod)
        if situation == "penalty":
            p_goal = 0.70 + 0.1 * (self.composure[slot] - 70) / 30
        blockers = self.team_slots(1 - team)
        lane, tpar = point_segment_distance(self.tf(self.pos[blockers], team), me, np.array([L, W / 2]))
        lane = np.where((tpar > 0.05) & ~self.is_gk[blockers], lane, 99.0)
        in_lane = int(np.sum(lane < 2.0))
        p_block = 0.0 if situation == "penalty" else min(0.65, 0.7 * math.exp(-float(lane.min()) / 1.8)
                                                         + 0.08 * max(0, in_lane - 1))
        r = self.rng.random()
        gy = self.rng.uniform(GOAL_Y_LOW + 0.3, GOAL_Y_HIGH - 0.3)
        recv: int | None = None
        if r < p_goal:
            resolution, aim, z = "goal", np.array([L + 0.5, gy]), self.rng.uniform(0.2, 2.2)
        elif r < p_goal + (1 - p_goal) * p_block:
            j = int(np.argmin(lane))
            resolution = "blocked"
            recv = int(blockers[j])
            aim, z = self.tf(self.pos[recv], team), 0.6
        else:
            on_target = self.rng.random() < min(0.6, 0.25 + 0.8 * brk.xg + 0.1 * (self.shooting[slot] - 70) / 30)
            if on_target and keeper:
                resolution, recv = "saved", keeper[0]
                aim, z = np.array([L - 0.5, gy]), self.rng.uniform(0.3, 2.0)
            else:
                post = self.rng.random() < 0.06
                resolution = "post" if post else "off_target"
                side = self.rng.choice([-1, 1])
                aim = np.array([L + 0.5, W / 2 + side * (GOAL_Y_HIGH - W / 2 + (0.0 if post else self.rng.uniform(0.4, 5)))])
                z = self.rng.uniform(0.2, 2.4) if post else self.rng.uniform(0.3, 4.5)
        foot_speed = self.rng.gauss(78 + 0.35 * self.shooting[slot] + 0.35 * max(0, brk.distance_m - 12), 9)
        speed_kmh = max(35.0, min(132.0, self.rng.gauss(58, 8) if header else foot_speed))
        start_abs = self.pos[slot].copy()
        end_abs = self.tf(aim[:2], team)
        travel = float(np.linalg.norm(aim[:2] - me))
        dur = max(0.15, travel / (speed_kmh / 3.6))
        assist = self.pass_chain[-1] if self.pass_chain and self.pass_chain[-1] != slot else None
        ev = dict(type=ET.SHOT, team=team, slot=slot, start=start_abs, end=end_abs, under_pressure=pressure > 0.4,
                  q=dict(situation=situation, body_part="head" if header else "foot", speed_kmh=round(speed_kmh, 1),
                         _truth_p_goal=round(p_goal, 4), _truth_xg=round(brk.xg, 4),
                         end_z=round(float(z), 2), distance_m=round(brk.distance_m, 1),
                         assist_candidate=self.slot_player[assist].id if assist is not None else None))
        self.flight = Flight("shot", start_abs, end_abs, self.t, self.t + dur, float(z) * 0.6, team, slot, recv,
                             resolution, ev, {"end_z": z, "assist": assist})
        self.owner = None

    # ------------------------------------------------------------------ ball flight
    def _advance_flight(self) -> None:
        f = self.flight
        assert f is not None
        s = min(1.0, (self.t - f.t0) / max(1e-6, f.t1 - f.t0))
        self.ball[:2] = f.start + (f.end - f.start) * s
        self.ball[2] = 4 * f.peak_z * s * (1 - s) if f.kind != "shot" else f.data.get("end_z", 0.5) * s
        if s < 1.0:
            return
        e = f.event
        q = e["q"]
        if f.kind in ("pass", "cross"):
            outcome = {"complete": "complete", "intercepted": "intercepted", "recovered": "incomplete",
                       "loose_won": "incomplete", "out": "out", "offside": "offside"}[f.resolution]
            self.emit(e["type"], e["team"], e["slot"], e["start"], e["end"], outcome=outcome,
                      receiver=f.receiver if f.resolution == "complete" else None, t=f.t0,
                      under_pressure=e["under_pressure"], **q)
            if f.resolution == "offside":
                recv = None
                for s_ in self.team_slots(f.team):
                    if self.slot_player[s_].id == q.get("intended_receiver_id"):
                        recv = s_
                self.emit(ET.OFFSIDE, f.team, recv, self.pos[recv] if recv is not None else f.end)
                self._award("free_kick", 1 - f.team, f.end, (10, 20))
                return
            if f.resolution == "out":
                self._ball_out(f.team, self._exit_point(f.start, f.end), f.passer)
                return
            assert f.receiver is not None
            if f.kind == "cross" and f.resolution == "intercepted" and self.rng.random() < 0.32:
                # Defender heads the cross behind for a corner.
                self.emit(ET.CLEARANCE, int(self.slot_team[f.receiver]), f.receiver, self.pos[f.receiver],
                          outcome="out", body_part="head")
                corner_y = 0.0 if f.end[1] < W / 2 else W
                self._award("corner", f.team, np.array([L if self.direction(f.team) == 1 else 0.0, corner_y]),
                            (30, 48))
                return
            if self.slot_team[f.receiver] != f.team:
                if f.resolution == "intercepted":
                    self.emit(ET.INTERCEPTION, int(self.slot_team[f.receiver]), f.receiver, self.pos[f.receiver])
                    self.give_ball(f.receiver)
                else:
                    self.give_ball(f.receiver, reason="recovery")
            else:
                self.give_ball(f.receiver)
                if f.kind == "cross":
                    self._after_cross_reception(f.receiver, f.data.get("set_piece"))
        elif f.kind == "clearance":
            self.emit(ET.CLEARANCE, e["team"], e["slot"], e["start"], e["end"], t=f.t0, under_pressure=True)
            if f.resolution == "out":
                self._ball_out(f.team, self._exit_point(f.start, f.end), f.passer)
            else:
                assert f.receiver is not None
                self.give_ball(f.receiver, reason="recovery")
        else:
            self._resolve_shot(f)

    def _after_cross_reception(self, slot: int, set_piece: str | None) -> None:
        team = int(self.slot_team[slot])
        me = self.tf(self.pos[slot], team)
        if in_box(me[0], me[1]) and self.rng.random() < (0.55 if set_piece == "corner" else 0.4):
            pressure, _, _ = self.pressure_on(slot)
            self._shoot(slot, pressure=pressure, situation=set_piece or "open_play", header=True)

    def _exit_point(self, start: np.ndarray, end: np.ndarray) -> np.ndarray:
        d = end - start
        ts = []
        for axis, lim in ((0, 0.0), (0, L), (1, 0.0), (1, W)):
            if abs(d[axis]) > 1e-9:
                tt = (lim - start[axis]) / d[axis]
                if 0 <= tt <= 1:
                    ts.append(tt)
        tt = min(ts) if ts else 1.0
        p = start + d * tt
        return np.array([min(max(p[0], 0.0), L), min(max(p[1], 0.0), W)])

    def _resolve_shot(self, f: Flight) -> None:
        e, q = f.event, f.event["q"]
        team, slot = f.team, f.passer
        outcome = f.resolution
        assist = f.data.get("assist")
        q = dict(q)
        q.pop("assist_candidate", None)
        q["assist_id"] = self.slot_player[assist].id if (assist is not None and outcome == "goal") else None
        self.emit(ET.SHOT, team, slot, e["start"], e["end"], outcome=outcome, t=f.t0, under_pressure=e["under_pressure"],
                  **q)
        if outcome == "goal":
            self.score[team] += 1
            self.emit(ET.GOAL, team, slot, e["start"], outcome="goal", assist_id=q["assist_id"],
                      home_score=self.score[0], away_score=self.score[1], situation=q["situation"])
            self.restart = Restart("kick_off", 1 - team, np.array([L / 2, W / 2]), self.t + self.rng.uniform(65, 95))
            self.owner = None
            self.flight = None
            self.ball[:] = (L / 2, W / 2, 0)
        elif outcome == "saved":
            keeper = f.receiver
            assert keeper is not None
            self.emit(ET.KEEPER_SAVE, 1 - team, keeper, self.pos[keeper], outcome="saved",
                      shot_speed_kmh=q["speed_kmh"])
            r = self.rng.random()
            if r < 0.55:
                self.give_ball(keeper)
                self.next_decision_t = self.t + self.rng.uniform(2.5, 6.0)
            elif r < 0.75:
                corner_y = 0.0 if self.pos[keeper][1] < W / 2 else W
                self._award("corner", team, np.array([L if self.direction(team) == 1 else 0.0, corner_y]), (30, 48))
            else:
                cands = np.where(self.active)[0]
                d = np.linalg.norm(self.pos[cands] - self.pos[keeper], axis=1) + self.np_rng.uniform(0, 6, len(cands))
                d[cands == keeper] = 99
                self.give_ball(int(cands[int(np.argmin(d))]), reason="recovery")
        elif outcome == "blocked":
            blocker = f.receiver
            assert blocker is not None
            r = self.rng.random()
            if r < 0.15:
                corner_y = 0.0 if self.pos[blocker][1] < W / 2 else W
                self._award("corner", team, np.array([L if self.direction(team) == 1 else 0.0, corner_y]), (30, 48))
            elif r < 0.7:
                self.give_ball(blocker, reason="recovery")
            else:
                cands = self.team_slots(team)
                d = np.linalg.norm(self.pos[cands] - self.pos[blocker], axis=1) + self.np_rng.uniform(0, 6, len(cands))
                self.give_ball(int(cands[int(np.argmin(d))]))
        else:  # off target or post
            if outcome == "post" and self.rng.random() < 0.5:
                cands = np.where(self.active)[0]
                d = np.linalg.norm(self.pos[cands] - f.end, axis=1) + self.np_rng.uniform(0, 6, len(cands))
                self.give_ball(int(cands[int(np.argmin(d))]), reason="recovery")
                return
            defending = 1 - team
            spot = self.tf(np.array([5.5, W / 2 + self.rng.choice([-9.0, 9.0])]), defending)
            self._award("goal_kick", defending, spot, (22, 38))

    # ------------------------------------------------------------------ movement
    def _move_players(self) -> None:
        targets = np.zeros((22, 2))
        urgency = np.zeros(22)
        ball_xy = self.ball[:2]
        poss = self.poss_team if self.owner is not None or self.flight is not None else None
        if self.flight is not None and self.flight.kind != "shot":
            poss = self.flight.team
        for team in (0, 1):
            slots = self.team_slots(team)
            tac = self.teams[team].tactics
            push = self._game_state_push(team)
            b = self.tf(ball_xy, team)
            anc = self.anchor[slots]
            depth = np.clip((anc[:, 0] - 0.1) / 0.82, 0, 1)
            if self.restart is not None:
                tgt, urg = self._restart_shape(team, slots, anc, depth, b)
            elif poss == team:
                tgt, urg = self._attacking_shape(team, slots, anc, depth, b, tac, push)
            else:
                tgt, urg = self._defending_shape(team, slots, anc, depth, b, tac, push)
            # Goalkeeper.
            gk_mask = self.is_gk[slots]
            if gk_mask.any():
                if poss != team:
                    gx = 3.0 + min(13.0, max(0.0, (b[0] - 25) * 0.1))
                else:
                    gx = 5.0 + min(20.0, max(0.0, (b[0] - 30) * 0.18))
                tgt[gk_mask] = (gx, W / 2 + (b[1] - W / 2) * 0.22)
            np.clip(tgt[:, 0], 0.5, L - 0.5, out=tgt[:, 0])
            np.clip(tgt[:, 1], 0.5, W - 0.5, out=tgt[:, 1])
            targets[slots] = self.tf(tgt, team)
            urgency[slots] = urg

        # Ball carrier and flight receiver.
        if self.owner is not None:
            o = self.owner
            if self.carry_target is not None:
                targets[o] = self.carry_target
            else:
                targets[o] = self.pos[o] + self.vel[o] * 0.3
            urgency[o] = 0.55
        if self.flight is not None and self.flight.receiver is not None and self.flight.kind != "shot":
            targets[self.flight.receiver] = self.flight.end
            urgency[self.flight.receiver] = 1.0

        # Slowly drifting personal offset makes movement less robotic.
        self.wobble += (-self.wobble / 6.0) * DT + self.np_rng.normal(0, 1.1, (22, 2)) * math.sqrt(DT)
        targets += self.wobble * (urgency < 0.5)[:, None]

        if self.frame_no % 10 == 0:
            self.fatigue = np.array([self._fatigue(s) for s in range(22)])
        vmax_sprint = (6.6 + 2.9 * self.pace / 100) * (1 - 0.18 * self.fatigue)
        vmax_jog = 3.6 + 0.8 * self.pace / 100
        vmax = vmax_jog + (vmax_sprint - vmax_jog) * urgency
        if self.owner is not None:
            vmax[self.owner] = (4.6 + 2.4 * self.pace[self.owner] / 100 * self.dribbling[self.owner] / 100)
        delta = targets - self.pos
        dist = np.linalg.norm(delta, axis=1)
        speed = np.minimum(vmax, 0.9 * dist)
        desired = np.where(dist[:, None] > 1e-6, delta / np.maximum(dist, 1e-6)[:, None] * speed[:, None], 0.0)
        dv = desired - self.vel
        acc = np.linalg.norm(dv, axis=1)
        max_dv = 4.2 * DT
        scale = np.where(acc > max_dv, max_dv / np.maximum(acc, 1e-9), 1.0)
        self.vel += dv * scale[:, None]
        self.vel[~self.active] = 0
        step = self.vel * DT
        self.pos += step
        self.pos[:, 0] = np.clip(self.pos[:, 0], -1, L + 1)
        self.pos[:, 1] = np.clip(self.pos[:, 1], -1, W + 1)
        self.dist_covered += np.linalg.norm(step, axis=1) * self.active
        if self.owner is not None:
            heading = self.vel[self.owner]
            n = np.linalg.norm(heading)
            self.ball[:2] = self.pos[self.owner] + (heading / n * 0.5 if n > 0.3 else 0)
            self.ball[2] = 0.0
            if self.carry_target is not None and np.linalg.norm(self.carry_target - self.pos[self.owner]) < 1.0:
                self.carry_target = None

    def _attacking_shape(self, team: int, slots: np.ndarray, anc: np.ndarray, depth: np.ndarray, b: np.ndarray,
                         tac: dict[str, float], push: float) -> tuple[np.ndarray, np.ndarray]:
        back = min(58.0, max(14.0, b[0] - 32 + 14 * tac["line"] + 8 * push))
        span = 44 + 8 * tac["width"]
        width = 46 + 18 * tac["width"]
        tgt = np.column_stack([back + depth * span, W / 2 + (anc[:, 1] - 0.5) * width + 0.12 * (b[1] - W / 2)])
        offside = self.offside_line(team)
        np.minimum(tgt[:, 0], offside - 0.8, out=tgt[:, 0])
        urg = np.zeros(len(slots))
        # Attacking runs in behind: occasional, by forwards, when the ball is beyond our own third.
        if b[0] > 38:
            idle = self.is_attacker[slots] & (self.run_until[slots] <= self.t)
            start = idle & (self.np_rng.random(len(slots)) < 0.0035 * (1 + tac["directness"]))
            self.run_until[slots[start]] = self.t + 2.6
            runners = self.run_until[slots] > self.t
            tgt[runners, 0] = min(offside + 12, L - 4)
            urg[runners] = 1.0
        # Support: the two nearest team-mates offer an angle to the ball carrier.
        if self.owner is not None and self.slot_team[self.owner] == team:
            d = np.linalg.norm(self.tf(self.pos[slots], team) - b, axis=1)
            d[slots == self.owner] = 999
            near = np.argsort(d)[:2]
            side = np.where(anc[near, 1] > 0.5, 8.0, -8.0)
            support = np.column_stack([np.full(len(near), b[0] + 6.0), b[1] + side])
            tgt[near] = 0.5 * tgt[near] + 0.5 * support
        return tgt, urg

    def _defending_shape(self, team: int, slots: np.ndarray, anc: np.ndarray, depth: np.ndarray, b: np.ndarray,
                         tac: dict[str, float], push: float) -> tuple[np.ndarray, np.ndarray]:
        line = 16 + 24 * tac["line"] + 0.22 * (b[0] - L / 2) + 6 * push
        back = min(50.0, max(6.0, min(line, b[0] - 8)))
        if b[0] < 38:  # ball near our box: drop into a deep, narrow block protecting the six-yard area
            back = min(back, 5.5 + 0.3 * max(0.0, b[0] - 8))
        span = 27 + 8 * (1 - tac["line"]) - (8 if b[0] < 38 else 0)
        width = 34 + 14 * tac["width"] - (8 if b[0] < 38 else 0)
        tgt = np.column_stack([back + depth * span, W / 2 + (anc[:, 1] - 0.5) * width + 0.38 * (b[1] - W / 2)])
        urg = np.zeros(len(slots))
        pos_tf = self.tf(self.pos[slots], team)
        # Recover goal-side when the ball is behind you.
        urg[pos_tf[:, 0] > b[0] + 3] = 0.6
        if b[0] < 38:  # ball near our box: everyone sprints into shape
            urg[:] = np.maximum(urg, 0.5)
        # Marking: blend towards the nearest opponent near your zone (vectorised).
        opp_tf = self.tf(self.pos[self.team_slots(1 - team)], team)
        d = np.linalg.norm(tgt[:, None, :] - opp_tf[None, :, :], axis=2)
        j = np.argmin(d, axis=1)
        dmin = d[np.arange(len(slots)), j]
        mark = (dmin < 11) & ~self.is_gk[slots]
        goal_side = opp_tf[j] + np.array([-1.5, 0.0])
        # Mark tighter the closer the opponent is to our goal.
        weight = np.where(opp_tf[j][:, 0] < 30, 0.75, 0.45)[:, None]
        tgt[mark] = (1 - weight[mark]) * tgt[mark] + weight[mark] * goal_side[mark]
        # Pressing: nearest one or two go to the ball when it's in the team's pressing zone.
        if b[0] < 30 + 75 * (tac["press"] + 0.2 * push) or self.flight is not None:
            dball = np.linalg.norm(pos_tf - b, axis=1)
            dball[self.is_gk[slots]] = 999
            n_press = 2 if (tac["press"] > 0.6 and b[0] > 40) or b[0] < 35 else 1
            press = np.argsort(dball)[:n_press]
            tgt[press] = b + np.array([-0.8, 0.0])
            urg[press] = 1.0
        return tgt, urg

    def _restart_shape(self, team: int, slots: np.ndarray, anc: np.ndarray, depth: np.ndarray,
                       b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        r = self.restart
        assert r is not None
        attacking = r.team == team
        spot_tf = self.tf(r.spot, team)
        box_set_piece = r.kind == "corner" or (
            r.kind == "free_kick" and (spot_tf[0] > 75 if attacking else spot_tf[0] < 30))
        if r.kind == "kick_off":
            x = np.clip(1.5 + depth * 46, 1, L / 2 - 1.0)
            tgt = np.column_stack([x, anc[:, 1] * W])
        elif r.kind == "penalty":
            x = np.full(len(slots), L - 20.0 if attacking else 20.0)
            tgt = np.column_stack([x, W / 2 + (anc[:, 1] - 0.5) * 30])
        elif box_set_piece:
            if attacking:
                # Most players attack the box; the two deepest outfielders hold at halfway.
                tgt = np.column_stack([L - 7.0 - 5.0 * (1 - depth), W / 2 + (anc[:, 1] - 0.5) * 24])
                outfield = np.where(~self.is_gk[slots])[0]
                stay = outfield[np.argsort(depth[outfield])[:2]]
                tgt[stay, 0] = L / 2 + 3
            else:
                tgt = np.column_stack([3.0 + 7.0 * (1 - depth), W / 2 + (anc[:, 1] - 0.5) * 22])
                tgt[int(np.argmax(depth)), 0] = 38.0  # one outlet stays up for the counter
        else:
            line = np.clip(b[0] - 25, 10, 55)
            tgt = np.column_stack([line + depth * 40, W / 2 + (anc[:, 1] - 0.5) * 50 + 0.25 * (b[1] - W / 2)])
        urg = np.zeros(len(slots))
        if attacking:
            d = np.linalg.norm(self.tf(self.pos[slots], team) - self.tf(r.spot, team), axis=1)
            if r.kind == "goal_kick":
                gk = np.where(self.is_gk[slots])[0]
                if len(gk):
                    tgt[gk[0]] = self.tf(r.spot, team)
                    urg[gk[0]] = 0.5
            else:
                d[self.is_gk[slots]] = 999
                i = int(np.argmin(d))
                tgt[i] = self.tf(r.spot, team)
                urg[i] = 0.5
        if self.is_gk[slots].any() and not (attacking and r.kind == "goal_kick"):
            tgt[self.is_gk[slots]] = np.array([3.0, W / 2])
        return tgt, urg

    # ------------------------------------------------------------------ output
    def frame(self) -> dict:
        pos = np.round(self.pos, 2).tolist()
        speeds = np.round(np.linalg.norm(self.vel, axis=1), 2).tolist()
        players = [(self.slot_player[s].id, pos[s][0], pos[s][1], speeds[s]) for s in range(22) if self.active[s]]
        return {
            "match_id": self.match_id,
            "frame": self.frame_no,
            "t": round(self.t, 2),
            "period": self.period,
            "clock": round(self.clock(), 2),
            "ball": (round(float(self.ball[0]), 2), round(float(self.ball[1]), 2), round(float(self.ball[2]), 2)),
            "ball_owner": self.slot_player[self.owner].id if self.owner is not None else None,
            "players": players,
        }

    def meta(self) -> dict:
        h, a = self.clubs
        return {
            "match_id": self.match_id,
            "home": h.id, "away": a.id, "home_name": h.name, "away_name": a.name,
            "venue": h.ground, "seed": self.seed,
            "home_lineup": self.lineups[0], "away_lineup": self.lineups[1],
            "home_subs": [p.id for p in self.teams[0].subs_left], "away_subs": [p.id for p in self.teams[1].subs_left],
            "home_formation": h.formation, "away_formation": a.formation,
        }
