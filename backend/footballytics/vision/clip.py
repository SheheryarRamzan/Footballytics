"""Ground truth for auto-eventing: a window of one simulated match, ready to render and to score against."""

from __future__ import annotations

import numpy as np

from ..league import League, generate_league
from ..schema import public_event
from ..sim.engine import MatchSim
from ..sim.matchday import fixtures, match_id_for

GK_KIT = ("#facc15", "#111827", "#facc15")  # same as the live 3D view: both keepers in yellow


def find_fixture(league: League, matchday: int, match: str) -> tuple[str, str, int]:
    """'HBC-KGA', 'md09-HBC-KGA' or a single club code -> (home, away, fixture index used for the seed)."""
    want = match.split("-")[-2:] if "-" in match else [match]
    for i, (h, a) in enumerate(fixtures(league)[matchday - 1]):
        if want == [h, a] or (len(want) == 1 and want[0] in (h, a)):
            return h, a, i
    raise KeyError(f"no fixture {match} on matchday {matchday}")


def busiest_window(matchday: int, match: str, seconds: float, league: League | None = None) -> float:
    """Start (seconds of play) of the window with the most passes, preferring windows that include a shot."""
    league = league or generate_league()
    home, away, i = find_fixture(league, matchday, match)
    sim = MatchSim(league, home, away, match_id_for(matchday, home, away), seed=10_000 * matchday + i)
    passes, shots = [], []
    for _, evs in sim.run():
        for e in evs:
            if e["type"] == "pass":
                passes.append(e["t"])
            elif e["type"] == "shot":
                shots.append(e["t"])
    p, s = np.array(passes), np.array(shots)
    best, best_score = 0.0, -1.0
    for start in np.arange(60.0, max(61.0, p.max() - seconds), 5.0):  # skip the kick-off minute
        n = ((p >= start) & (p < start + seconds)).sum()
        shot = ((s >= start + 2) & (s < start + seconds - 3)).any()
        score = n + (8 if shot else 0)
        if score > best_score:
            best, best_score = float(start), score
    return best


def _interp(a: dict, b: dict, w: float) -> tuple[list, list]:
    """Players [id, x, y, km/h] and ball [x, y, z] a fraction ``w`` of the way from frame a to frame b."""
    pa = {p[0]: p for p in a["players"]}
    players = []
    for pid, x, y, v in b["players"]:
        p = pa.get(pid)
        if p is None or abs(p[1] - x) + abs(p[2] - y) > 8:  # a substitute appearing: no interpolation
            players.append([pid, x, y, v * 3.6])
        else:
            players.append([pid, p[1] + (x - p[1]) * w, p[2] + (y - p[2]) * w, (p[3] + (v - p[3]) * w) * 3.6])
    ba, bb = np.array(a["ball"]), np.array(b["ball"])
    ball = bb if np.abs(ba[:2] - bb[:2]).sum() > 15 else ba + (bb - ba) * w
    return players, [round(float(c), 3) for c in ball]


def make_clip(matchday: int = 9, match: str = "HBC-KGA", start_s: float = 600.0, seconds: float = 40.0,
              fps: int = 25, league: League | None = None) -> dict:
    """Simulate the match up to ``start_s`` seconds of play and cut ``seconds`` of it.

    Same seed as the live matchday (hub.py), so the clip is the match fans watched. Returns the 10 Hz tracking and the
    events in the window (the answer key) plus the frames to render at ``fps``.
    """
    league = league or generate_league()
    home, away, i = find_fixture(league, matchday, match)
    mid = match_id_for(matchday, home, away)
    sim = MatchSim(league, home, away, mid, seed=10_000 * matchday + i)
    end = start_s + seconds
    tracking: list[dict] = []
    events: list[dict] = []
    for frame, evs in sim.run():
        t = frame["t"]
        if start_s - 0.1 <= t <= end + 0.1:
            tracking.append(frame)
        events += [e for e in evs if start_s <= e["t"] <= end]
        if t > end + 6:  # events are published once their outcome is known: wait for late ones
            break
    if len(tracking) < 2:
        raise ValueError(f"match {mid} has no play between {start_s}s and {end}s")

    video = []
    times = np.arange(tracking[0]["t"], tracking[-1]["t"], 1 / fps)
    ts = np.array([f["t"] for f in tracking])
    for t in times:
        k = int(np.clip(np.searchsorted(ts, t, side="right") - 1, 0, len(ts) - 2))
        w = float(np.clip((t - ts[k]) / max(1e-6, ts[k + 1] - ts[k]), 0, 1))
        players, ball = _interp(tracking[k], tracking[k + 1], w)
        video.append({"t": round(float(t), 3), "p": [[p[0], round(p[1], 3), round(p[2], 3), round(p[3], 2)]
                                                      for p in players], "b": ball})

    ids = sorted({p[0] for f in tracking for p in f["players"]})
    players = []
    for pid in ids:
        pl = league.players[pid]
        club = league.clubs[pl.club_id]
        gk = pl.group == "GK"
        shirt, shorts, socks = GK_KIT if gk else (club.primary, club.secondary, club.primary)
        players.append({"id": pid, "name": pl.short_name, "number": pl.number, "team": pl.club_id,
                        "side": 0 if pl.club_id == home else 1, "gk": gk, "shirt": shirt, "shorts": shorts,
                        "socks": socks})
    meta = sim.meta()
    return {
        "meta": {"match_id": mid, "matchday": matchday, "home": home, "away": away, "home_name": meta["home_name"],
                 "away_name": meta["away_name"], "start_t": start_s, "seconds": seconds, "fps": fps, "track_hz": 10},
        "players": players,
        "tracking": [{"t": f["t"], "clock": f["clock"], "ball": list(f["ball"]), "owner": f["ball_owner"],
                      "players": [list(p) for p in f["players"]]} for f in tracking],
        "events": [public_event(e) for e in events],
        "video": video,
    }
