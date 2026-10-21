"""Auto-eventing: possession, passes, shots and speed metrics inferred from the tracks alone (no event feed)."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np

from ..engine.metrics import SPRINT_KMH, TAG_SPEED_KMH
from .track import Track

CONTROL_M = 1.6  # ball within this distance of a player's feet = that player controls it
DRIBBLE_KMH = 28.0  # a controlled ball moves at running pace; faster means it is travelling between players
FLIGHT_KMH = 22.0  # a ball moving faster than this is in flight ...
PASS_KMH = 32.0  # ... and one whose median flight speed beats this was struck, not dribbled (sim passes: >= 37 km/h)
SHOT_KMH = 50.0
GOAL_Y = (34.0 - 3.66, 34.0 + 3.66)


@dataclass
class Segment:
    owner: int  # track id
    team: int
    start: int  # video frame
    end: int


def positions_at(tracks: list[Track], n_frames: int, max_gap: int) -> dict[int, list[tuple[float, float] | None]]:
    """Each track's pitch position at every video frame, interpolated between detection frames (short gaps only)."""
    out = {}
    for tr in tracks:
        ks = sorted(tr.points)
        series: list[tuple[float, float] | None] = [None] * n_frames
        for a, b in zip(ks, ks[1:] + [None]):
            series[a] = tr.points[a]
            if b is not None and b - a <= max_gap:
                (x0, y0), (x1, y1) = tr.points[a], tr.points[b]
                for k in range(a + 1, b):
                    w = (k - a) / (b - a)
                    series[k] = (x0 + (x1 - x0) * w, y0 + (y1 - y0) * w)
        out[tr.id] = series
    return out


def smooth_speed(series: list[tuple[float, float] | None], fps: float, window: int) -> list[float | None]:
    """Speed (km/h) from a position series: centred moving average, then central differences."""
    n = len(series)
    pts = np.full((n, 2), np.nan)
    for k, p in enumerate(series):
        if p is not None:
            pts[k] = p
    half = window // 2
    sm = np.full((n, 2), np.nan)
    for k in range(n):
        seg = pts[max(0, k - half):k + half + 1]
        if not np.isnan(seg).any():
            sm[k] = seg.mean(axis=0)
    out: list[float | None] = [None] * n
    for k in range(1, n - 1):
        if not (np.isnan(sm[k - 1]).any() or np.isnan(sm[k + 1]).any()):
            out[k] = float(np.linalg.norm(sm[k + 1] - sm[k - 1]) * fps / 2 * 3.6)
    return out


def possession(ball: list[tuple[float, float] | None], ball_kmh: list[float | None],
               pos: dict[int, list[tuple[float, float] | None]], teams: dict[int, int], fps: float) -> list[Segment]:
    owner: list[int | None] = []
    cur: int | None = None
    for k, b in enumerate(ball):
        if b is None or (ball_kmh[k] is not None and ball_kmh[k] > DRIBBLE_KMH):
            cur = None
            owner.append(None)
            continue
        dist = {tid: float(np.hypot(s[k][0] - b[0], s[k][1] - b[1])) for tid, s in pos.items() if s[k] is not None}
        best = min(dist, key=dist.get, default=None)
        if cur is not None and dist.get(cur, 99.0) <= CONTROL_M + 0.6:
            # hysteresis: in a duel the ball stays with its player unless someone is clearly closer
            if best != cur and dist[best] <= CONTROL_M and dist[best] < dist[cur] - 0.6:
                cur = best
        else:
            cur = best if best is not None and dist[best] <= CONTROL_M else None
        owner.append(cur)
    segs: list[Segment] = []
    for k, o in enumerate(owner):
        if o is None:
            continue
        if segs and segs[-1].owner == o and k - segs[-1].end <= 3:
            segs[-1].end = k
        else:
            segs.append(Segment(o, teams[o], k, k))
    min_len = max(2, int(0.16 * fps))
    return [s for s in segs if s.end - s.start + 1 >= min_len]


def dist2(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def is_shot(p0: tuple[float, float], p1: tuple[float, float], kmh: float) -> bool:
    """Struck hard, from within 30 m of a goal, and heading for its mouth (with a margin for deflections)."""
    dx = p1[0] - p0[0]
    if kmh < SHOT_KMH or abs(dx) < 1.0:
        return False
    gx = 105.0 if dx > 0 else 0.0
    if abs(gx - p0[0]) > 30.0:
        return False
    y_at = p0[1] + (p1[1] - p0[1]) * (gx - p0[0]) / dx
    return GOAL_Y[0] - 2.0 <= y_at <= GOAL_Y[1] + 2.0


def flights(ball: list[tuple[float, float] | None], ball_kmh: list[float | None], fps: float
            ) -> list[tuple[int, int]]:
    """Frame spans where the ball travels faster than a dribble (short dips are bridged)."""
    out, k, n = [], 0, len(ball)
    while k < n:
        if ball_kmh[k] is not None and ball_kmh[k] >= FLIGHT_KMH:
            j, last = k, k
            while j < n and (j - last) <= 2:
                if ball_kmh[j] is not None and ball_kmh[j] >= FLIGHT_KMH:
                    last = j
                j += 1
            if last - k + 1 >= max(3, int(0.2 * fps)) and ball[k] is not None and ball[last] is not None:
                out.append((k, last))
            k = last + 1
        else:
            k += 1
    return out


def nearest_detection(ball: list, dets_at: dict, frames, radius: float, offset: np.ndarray,
                      exclude: int | None = None) -> tuple[int | None, int | None]:
    """(track, team) of the player detected nearest a point on the ball's path, voted over a few frames.

    The team is the detections' own shirt colour, not the track's: when a marker and a ball carrier overlap, a track
    can swallow both, but each detection still shows whose shirt it is.
    """
    from collections import Counter

    tracks_v: Counter = Counter()
    teams_v: Counter = Counter()
    for k in frames:
        b = ball[k] if 0 <= k < len(ball) else None
        if b is None or k not in dets_at:
            continue
        x, y = b[0] + float(offset[0]), b[1] + float(offset[1])
        cands = [(float(np.hypot(d.x - x, d.y - y)), d) for d in dets_at[k] if d.track != exclude]
        if cands:
            dist, d = min(cands, key=lambda c: c[0])
            if dist <= radius:
                tracks_v[d.track] += 1
                teams_v[d.shirt_team] += 1
    if not tracks_v:
        return None, None
    return tracks_v.most_common(1)[0][0], teams_v.most_common(1)[0][0]


def nearest_player(ball: list, pos: dict[int, list], frames, radius: float, exclude: int | None = None,
                   offset: np.ndarray | None = None) -> int | None:
    """The track most often nearest the ball (shifted by ``offset``, within ``radius``) over a few frames.

    A vote, so one bad frame does not decide it.
    """
    from collections import Counter

    votes: Counter = Counter()
    for k in frames:
        b = ball[k] if 0 <= k < len(ball) else None
        if b is None:
            continue
        if offset is not None:
            b = (b[0] + float(offset[0]), b[1] + float(offset[1]))
        dist = {tid: float(np.hypot(s[k][0] - b[0], s[k][1] - b[1])) for tid, s in pos.items()
                if s[k] is not None and tid != exclude}
        if dist:
            tid = min(dist, key=dist.get)
            if dist[tid] <= radius:
                votes[tid] += 1
    return votes.most_common(1)[0][0] if votes else None


def infer_events(tracks: list[Track], ball: list[tuple[float, float] | None], times: list[float], fps: float,
                 det_stride: int, dets: list | None = None) -> dict:
    n = len(ball)
    teams = {tr.id: tr.team for tr in tracks}
    pos = positions_at(tracks, n, max_gap=int(0.6 * fps))
    ball_kmh = smooth_speed(ball, fps, window=5)
    segs = possession(ball, ball_kmh, pos, teams, fps)

    dets_at: dict[int, list] = {}
    for det in dets or []:
        dets_at.setdefault(det.k, []).append(det)
    passes, turnovers, shots = [], [], []
    prev: tuple[int, tuple[float, float], int | None] | None = None  # (end frame, end point, receiving team)
    for k0, k1 in flights(ball, ball_kmh, fps):
        p0, p1 = ball[k0], ball[k1]
        length = float(np.hypot(p1[0] - p0[0], p1[1] - p0[1]))
        speed = float(np.median([v for v in ball_kmh[k0:k1 + 1] if v is not None]))  # robust to one bad frame
        d = (np.array(p1) - np.array(p0)) / max(length, 1e-6)
        passer, p_team = nearest_detection(ball, dets_at, range(max(0, k0 - 5), k0 + 2), 2.5, -0.8 * d)
        # possession continuity: whoever received the last ball and kept it is the one passing it on, even when a
        # marker standing in front of them is what the camera sees at the moment of the pass
        if prev and prev[2] is not None and (k0 - prev[0]) / fps < 5.0 and dist2(p0, prev[1]) < 8.0:
            p_team = prev[2]
        if is_shot(p0, p1, speed):
            shots.append({"t": round(times[k0], 2), "track": passer, "team": p_team, "x": round(p0[0], 1),
                          "y": round(p0[1], 1), "speed_kmh": round(speed, 1), "toward_goal_x": 105.0 if d[0] > 0 else 0.0})
            prev = None
            continue
        if length < 3.0 or speed < PASS_KMH or passer is None:
            continue
        # the receiver is ahead of where the ball stops (not the marker beside it)
        receiver, r_team = nearest_detection(ball, dets_at, range(k1 - 1, min(n, k1 + 7)), 2.5, 0.5 * d,
                                             exclude=passer)
        prev = (k1, p1, r_team)
        ev = {"t": round(times[k0], 2), "t_end": round(times[k1], 2), "from_track": passer, "to_track": receiver,
              "team": p_team, "x": round(p0[0], 1), "y": round(p0[1], 1), "end_x": round(p1[0], 1),
              "end_y": round(p1[1], 1), "length_m": round(length, 1), "speed_kmh": round(speed, 1)}
        if receiver is not None and r_team == p_team:
            passes.append(ev)
        elif receiver is not None:
            turnovers.append(ev)

    players = {}
    for tr in tracks:
        ks = sorted(tr.points)
        if len(ks) < 5:
            continue
        sp = smooth_speed([tr.points.get(k) for k in range(ks[0], ks[-1] + 1, det_stride)], fps / det_stride, 9)
        vals = [v for v in sp if v is not None]
        if not vals:
            continue
        dist = sum(np.hypot(tr.points[b][0] - tr.points[a][0], tr.points[b][1] - tr.points[a][1])
                   for a, b in itertools.pairwise(ks) if b - a <= det_stride * 3)
        sprint_frames = int(0.7 * fps / det_stride)
        sprints, run = 0, 0
        for v in sp:
            run = run + 1 if v is not None and v >= SPRINT_KMH else 0
            sprints += run == sprint_frames
        players[tr.id] = {"team": tr.team, "keeper": tr.keeper, "seen_s": round(len(ks) * det_stride / fps, 1),
                          "top_speed_kmh": round(max(vals), 1), "distance_m": round(float(dist), 1),
                          "sprints": sprints, "speed_tag": max(vals) >= TAG_SPEED_KMH}
    return {"possession": [s.__dict__ for s in segs], "passes": passes, "turnovers": turnovers, "shots": shots,
            "players": players, "ball_kmh": ball_kmh}
