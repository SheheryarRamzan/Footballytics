"""From per-frame detections to pitch tracks: calibration, team colours, multi-object and ball tracking.

Everything here uses only what a broadcast pipeline would have: the frames, the detector output and the camera
calibration (pitch-to-pixel homography). The simulator's answer key is only used later, in evaluate.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from .detect import Box, to_pitch


@dataclass
class Detection:
    k: int  # video frame index
    t: float
    box: Box
    x: float  # pitch metres (foot point through the homography)
    y: float
    color: np.ndarray  # mean shirt colour (Lab)
    team: int = -1  # 0 / 1: the track's majority team after tracking (shirt colour before)
    keeper: bool = False
    track: int = -1
    shirt_team: int = -1  # this detection's own shirt-colour team (kept: in duels it beats the track's majority)


@dataclass
class Track:
    id: int
    team: int
    points: dict[int, tuple[float, float]] = field(default_factory=dict)  # frame -> (x, y)
    keeper: bool = False
    votes: list[int] = field(default_factory=lambda: [0, 0])  # team votes from shirt colour

    def last(self) -> tuple[int, tuple[float, float]]:
        k = max(self.points)
        return k, self.points[k]

    def velocity(self, fps: float) -> tuple[float, float]:
        ks = sorted(self.points)[-4:]
        if len(ks) < 2:
            return 0.0, 0.0
        (x0, y0), (x1, y1) = self.points[ks[0]], self.points[ks[-1]]
        dt = (ks[-1] - ks[0]) / fps
        return (x1 - x0) / dt, (y1 - y0) / dt


def shirt_color(rgb: np.ndarray, b: Box) -> np.ndarray:
    """Mean Lab colour of the torso (upper body, centre strip), ignoring grass pixels."""
    import cv2

    h = b.y2 - b.y1
    y1, y2 = int(b.y1 + 0.18 * h), int(b.y1 + 0.42 * h)
    w = b.x2 - b.x1
    x1, x2 = int(b.x1 + 0.25 * w), int(b.x2 - 0.25 * w) + 1
    crop = rgb[max(0, y1):max(y1 + 1, y2), max(0, x1):max(x1 + 1, x2)]
    if crop.size == 0:
        return np.zeros(3)
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV).reshape(-1, 3)
    lab = cv2.cvtColor(crop, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(float)
    grass = (hsv[:, 0] > 35) & (hsv[:, 0] < 85) & (hsv[:, 1] > 80)
    pix = lab[~grass] if (~grass).sum() >= 3 else lab
    return pix.mean(axis=0)


def detections_for_frame(k: int, t: float, rgb: np.ndarray, H: np.ndarray, boxes: list[Box]) -> list[Detection]:
    out = []
    for b in boxes:
        x, y = to_pitch(H, *b.foot)
        if -3 <= x <= 108 and -3 <= y <= 71:  # on the pitch: drops crowd and bench false positives
            out.append(Detection(k, t, b, x, y, shirt_color(rgb, b)))
    return out


def assign_teams(dets: list[Detection]) -> dict:
    """Cluster shirt colours into two teams plus keepers (k-means, k=3); no prior knowledge of the kits."""
    import cv2

    X = np.array([d.color for d in dets], dtype=np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.2)
    _, labels, centers = cv2.kmeans(X, 3, None, crit, 5, cv2.KMEANS_PP_CENTERS)
    labels = labels.ravel()
    sizes = np.bincount(labels, minlength=3)
    order = np.argsort(-sizes)
    teams, keeper_c = order[:2], order[2]
    # the smallest cluster is the keepers only if it is clearly smaller; otherwise all three are outfield shades
    keepers_ok = sizes[keeper_c] < 0.25 * sizes[teams].min()
    mean_x = [np.mean([d.x for d, lab in zip(dets, labels) if lab == c]) for c in teams]
    left = 0 if mean_x[0] < mean_x[1] else 1  # the team defending the left goal sits deeper on average
    for d, lab in zip(dets, labels):
        if lab in teams:
            d.team = int(np.flatnonzero(teams == lab)[0])
        elif keepers_ok:
            d.keeper = True
            d.team = left if d.x < 52.5 else 1 - left
        else:
            d.team = int(np.argmin([np.linalg.norm(d.color - centers[c]) for c in teams]))
        d.shirt_team = d.team
    return {"centers": centers[teams].tolist(), "keepers": bool(keepers_ok), "left_team": int(left)}


def track_players(dets: list[Detection], fps: float, gate: float = 2.5, max_gap_s: float = 3.0,
                  team_penalty: float = 1.5) -> list[Track]:
    """Frame-to-frame assignment (Hungarian) in pitch coordinates with constant-velocity prediction.

    A lost track stays open for ``max_gap_s`` with a gate that grows with the gap, so players who leave the
    panning camera's view and come back usually keep their identity. Shirt colour is a soft cost (one misread
    colour does not break a track); each track takes its majority colour, and its detections inherit it.
    """
    by_k: dict[int, list[Detection]] = {}
    for d in dets:
        by_k.setdefault(d.k, []).append(d)
    tracks: list[Track] = []
    for k in sorted(by_k):
        frame = by_k[k]
        live = [tr for tr in tracks if (k - tr.last()[0]) / fps <= max_gap_s]
        cost = np.full((len(live), len(frame)), 1e6)
        for i, tr in enumerate(live):
            k0, (x0, y0) = tr.last()
            dt = (k - k0) / fps
            vx, vy = tr.velocity(fps)
            px, py = x0 + vx * min(dt, 0.6), y0 + vy * min(dt, 0.6)
            g = gate + 6.0 * dt  # up to ~6 m/s of unseen movement
            for j, d in enumerate(frame):
                dist = float(np.hypot(d.x - px, d.y - py)) + (team_penalty if d.team != tr.team else 0.0)
                if dist <= g:
                    cost[i, j] = dist + 0.5 * dt  # prefer recently seen tracks
        rows, cols = linear_sum_assignment(cost) if live and frame else ([], [])
        used = set()
        for i, j in zip(rows, cols):
            if cost[i, j] >= 1e6:
                continue
            tr, d = live[i], frame[j]
            tr.points[k] = (d.x, d.y)
            tr.keeper = tr.keeper or d.keeper
            tr.votes[d.team] += 1
            tr.team = int(np.argmax(tr.votes))
            d.track = tr.id
            used.add(j)
        for j, d in enumerate(frame):
            if j not in used:
                tr = Track(len(tracks), d.team, {k: (d.x, d.y)}, d.keeper)
                tr.votes[d.team] += 1
                d.track = tr.id
                tracks.append(tr)
    for d in dets:  # every detection carries its track's majority team
        if d.track >= 0:
            d.team = tracks[d.track].team
    return tracks


def ball_path(cands: list[list[tuple[float, float, float]]], Hs: list[np.ndarray], fps: float,
              players_at: list[list[tuple[float, float]]], max_gap_s: float = 3.0, vmax: float = 34.0
              ) -> list[tuple[float, float] | None]:
    """The most plausible ball trajectory through all frames' candidates (dynamic programming, whole clip).

    Each candidate earns a reward (more if it is round and at a player's feet); hops cost a little distance (no
    zig-zags), skipped frames cost a little, and no hop may need more than ``vmax`` m/s. A spurious white blob
    therefore cannot hijack the path for long, and the ball is found again after an occlusion or a lofted pass.
    """
    nodes: list[list[tuple[float, float, float]]] = []  # per frame: (x, y, reward)
    for k, cs in enumerate(cands):
        row = []
        for u, v, s in cs:
            x, y = to_pitch(Hs[k], u, v)
            near = min((np.hypot(x - px, y - py) for px, py in players_at[k]), default=99.0)
            row.append((x, y, 1.0 + 0.3 * s + (0.4 if near < 2.0 else 0.0)))
        nodes.append(row)
    max_gap = int(max_gap_s * fps)
    value: list[list[float]] = []
    back: list[list[tuple[int, int] | None]] = []
    for k, row in enumerate(nodes):
        vals, prevs = [], []
        for x, y, r in row:
            best, arg = r - 2.0, None  # starting a new path costs: short spurious paths lose
            for k0 in range(max(0, k - max_gap), k):
                gap = k - k0
                reach = vmax * gap / fps + 1.0
                for i0, (x0, y0, _) in enumerate(nodes[k0]):
                    d = float(np.hypot(x - x0, y - y0))
                    if d > reach:
                        continue
                    v = value[k0][i0] + r - 0.08 * d - 0.15 * (gap - 1) - (1.5 if gap > 0.5 * fps else 0.0)
                    if v > best:
                        best, arg = v, (k0, i0)
            vals.append(best)
            prevs.append(arg)
        value.append(vals)
        back.append(prevs)
    out: list[tuple[float, float] | None] = [None] * len(nodes)
    ends = [(v, k, i) for k, vs in enumerate(value) for i, v in enumerate(vs)]
    if not ends:
        return out
    _, k, i = max(ends)
    node: tuple[int, int] | None = (k, i)
    while node is not None:
        k, i = node
        out[k] = (nodes[k][i][0], nodes[k][i][1])
        node = back[k][i]
    return out


def track_ball(cands: list[list[tuple[float, float, float]]], Hs: list[np.ndarray], fps: float,
               players_at: list[list[tuple[float, float]]] | None = None, max_hold_s: float = 0.4
               ) -> list[tuple[float, float] | None]:
    """Pick the ball among each frame's candidates with a constant-velocity filter in pitch coordinates.

    Starts on a candidate at a player's feet; keeps the candidate nearest the prediction inside a gate that grows
    while the ball is unseen (hidden behind a player, or too fast to read); gives up after ``max_hold_s``.
    """
    out: list[tuple[float, float] | None] = []
    pos: np.ndarray | None = None
    vel = np.zeros(2)
    unseen = 0
    for k, cs in enumerate(cands):
        pts = [np.array(to_pitch(Hs[k], u, v)) for u, v, _ in cs]
        if pos is None:
            near = []
            for p, (_, _, s) in zip(pts, cs):
                feet = players_at[k] if players_at else []
                dmin = min((np.hypot(p[0] - x, p[1] - y) for x, y in feet), default=99.0)
                if dmin < 2.0:
                    near.append((dmin - s, p))
            if near:
                pos = min(near, key=lambda n: n[0])[1]
                vel[:] = 0
                unseen = 0
                out.append((float(pos[0]), float(pos[1])))
            else:
                out.append(None)
            continue
        pred = pos + vel / fps
        gate = 1.5 + 28.0 * (unseen + 1) / fps  # the ball can do 100 km/h
        best = min(((np.linalg.norm(p - pred), p) for p in pts), key=lambda n: n[0], default=(np.inf, None))
        if best[1] is not None and best[0] <= gate:
            new = best[1]
            v_new = (new - pos) * fps / (unseen + 1)
            vel = 0.5 * vel + 0.5 * v_new
            pos = new
            unseen = 0
            out.append((float(pos[0]), float(pos[1])))
        else:
            unseen += 1
            pos = pred
            if unseen / fps > max_hold_s:
                pos = None
                out.append(None)
            else:
                out.append(None)  # predicted only; gaps are interpolated later if short
    return out


def fill_gaps(series: list[tuple[float, float] | None], max_gap: int) -> list[tuple[float, float] | None]:
    """Linearly interpolate runs of None no longer than ``max_gap`` frames."""
    out = list(series)
    k = 0
    while k < len(out):
        if out[k] is None:
            j = k
            while j < len(out) and out[j] is None:
                j += 1
            if 0 < k and j < len(out) and j - k <= max_gap:
                a, b = np.array(out[k - 1]), np.array(out[j])
                for i in range(k, j):
                    w = (i - k + 1) / (j - k + 1)
                    p = a + (b - a) * w
                    out[i] = (float(p[0]), float(p[1]))
            k = j
        else:
            k += 1
    return out
