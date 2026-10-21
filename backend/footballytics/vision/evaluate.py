"""Score auto-eventing against the simulator's answer key (the clip's true tracking and events)."""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
from scipy.optimize import linear_sum_assignment

from .track import Detection, Track


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i + 1e-9)


def _match_times(pred: list[float], true: list[float], tol: float) -> list[tuple[int, int]]:
    if not pred or not true:
        return []
    cost = np.array([[abs(p - t) if abs(p - t) <= tol else 1e6 for t in true] for p in pred])
    rows, cols = linear_sum_assignment(cost)
    return [(i, j) for i, j in zip(rows, cols) if cost[i, j] < 1e6]


def _prf(tp: int, n_pred: int, n_true: int) -> dict:
    p = tp / n_pred if n_pred else None
    r = tp / n_true if n_true else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if n_pred and n_true else None)
    return {"tp": tp, "predicted": n_pred, "true": n_true, "precision": p, "recall": r, "f1": f}


def evaluate(clip: dict, render: dict, dets: list[Detection], tracks: list[Track], ball: list, events: dict,
             det_frames: list[int]) -> dict:
    clip["meta"]["fps"]
    video = clip["video"]
    frames = render["frames"]
    team_of = {p["id"]: p["team"] for p in clip["players"]}
    gt_pos = [{p[0]: (p[1], p[2], p[3]) for p in f["p"]} for f in video]

    # 1. detection, localisation, team, identity (on the frames the detector ran on)
    by_k = defaultdict(list)
    for d in dets:
        by_k[d.k].append(d)
    tp = n_det = n_gt = 0
    loc_err, pairs = [], []
    for k in det_frames:
        gt_ids = list(frames[k]["boxes"])
        gt_boxes = [frames[k]["boxes"][i] for i in gt_ids]
        ds = by_k.get(k, [])
        n_det += len(ds)
        n_gt += len(gt_boxes)
        if not ds or not gt_boxes:
            continue
        cost = np.array([[1 - _iou((d.box.x1, d.box.y1, d.box.x2, d.box.y2), g) for g in gt_boxes] for d in ds])
        rows, cols = linear_sum_assignment(cost)
        for i, j in zip(rows, cols):
            if cost[i, j] <= 0.5:
                tp += 1
                gid = gt_ids[j]
                gx, gy, _ = gt_pos[k][gid]
                loc_err.append(float(np.hypot(ds[i].x - gx, ds[i].y - gy)))
                pairs.append((ds[i], gid))
    detection = {"iou": 0.5, **_prf(tp, n_det, n_gt)}

    team_map = {}
    for team in (0, 1):
        votes = Counter(team_of[g] for d, g in pairs if d.team == team)
        team_map[team] = votes.most_common(1)[0][0] if votes else None
    team_acc = float(np.mean([team_map.get(d.team) == team_of[g] for d, g in pairs])) if pairs else None

    track_votes: dict[int, Counter] = defaultdict(Counter)
    for d, g in pairs:
        track_votes[d.track][g] += 1
    track_gt = {t: c.most_common(1)[0][0] for t, c in track_votes.items()}
    id_acc = float(np.mean([track_gt.get(d.track) == g for d, g in pairs])) if pairs else None
    seen_players = {g for _, g in pairs}
    long_tracks = [t for t in tracks if len(t.points) >= 5]

    # 2. ball (frames where the true ball is on screen and on the ground: a lofted ball has no ground position)
    vis = [k for k, f in enumerate(frames) if f["ball"] is not None and video[k]["b"][2] < 0.5]
    aerial = sum(1 for k, f in enumerate(frames) if f["ball"] is not None and video[k]["b"][2] >= 0.5)
    errs = []
    for k in vis:
        if ball[k] is not None:
            bx, by, _ = video[k]["b"]
            errs.append(float(np.hypot(ball[k][0] - bx, ball[k][1] - by)))
    ball_metrics = {"visible_frames": len(vis), "aerial_frames": aerial, "tracked_frames": len(errs),
                    "tracked_share": len(errs) / len(vis) if vis else None,
                    "within_2m_share": float(np.mean([e <= 2.0 for e in errs])) if errs else None,
                    "median_error_m": float(np.median(errs)) if errs else None}

    # 3. passes
    t0, t1 = clip["meta"]["start_t"], clip["meta"]["start_t"] + clip["meta"]["seconds"]
    times = np.array([f["t"] for f in video])

    def on_screen(pid: str, t: float) -> bool:
        k = int(np.clip(np.searchsorted(times, t), 0, len(frames) - 1))
        return pid in frames[k]["boxes"]

    lo, hi = t0 + 0.5, t1 - 1.5  # the same window for truth and predictions: a pass needs time to arrive
    attempts = [e for e in clip["events"] if e["type"] in ("pass", "cross") and lo <= e["t"] <= hi]
    for e in attempts:
        q = e.get("qualifiers") or {}
        flight = (q.get("length_m") or 10) / max(1.0, (q.get("speed_kmh") or 50) / 3.6) * 1.3
        e["_visible"] = on_screen(e["player_id"], e["t"]) and (
            e["receiver_id"] is None or on_screen(e["receiver_id"], e["t"] + flight))
    pred = sorted([{**p, "completed": True} for p in events["passes"] if lo <= p["t"] <= hi + 0.5] +
                  [{**p, "completed": False} for p in events["turnovers"] if lo <= p["t"] <= hi + 0.5],
                  key=lambda p: p["t"])
    m = _match_times([p["t"] for p in pred], [e["t"] for e in attempts], tol=1.0)
    vis_idx = {j for j, e in enumerate(attempts) if e["_visible"]}
    ground_idx = {j for j, e in enumerate(attempts) if (e.get("qualifiers") or {}).get("height") != "high"}

    def q(j: int, key: str):
        return (attempts[j].get("qualifiers") or {}).get(key)

    outcome_ok = [pred[i]["completed"] == (attempts[j]["outcome"] == "complete") for i, j in m]
    team_ok = [team_map.get(pred[i]["team"]) == attempts[j]["team_id"] for i, j in m]
    right_players = sum(1 for i, j in m if pred[i]["completed"] and attempts[j]["outcome"] == "complete"
                        and track_gt.get(pred[i]["from_track"]) == attempts[j]["player_id"]
                        and track_gt.get(pred[i]["to_track"]) == attempts[j]["receiver_id"])
    both_complete = sum(1 for i, j in m if pred[i]["completed"] and attempts[j]["outcome"] == "complete")
    spd = [abs(pred[i]["speed_kmh"] - q(j, "speed_kmh")) for i, j in m if pred[i]["speed_kmh"] and q(j, "speed_kmh")]
    lng = [abs(pred[i]["length_m"] - q(j, "length_m")) for i, j in m  # an interception cuts a pass short
           if q(j, "length_m") and pred[i]["completed"] and attempts[j]["outcome"] == "complete"]
    comp_pred = [i for i, p in enumerate(pred) if p["completed"]]
    comp_true = [j for j, e in enumerate(attempts) if e["outcome"] == "complete"]
    comp_tp = sum(1 for i, j in m if pred[i]["completed"] and attempts[j]["outcome"] == "complete")
    passes = {"tolerance_s": 1.0,
              "attempts": _prf(len(m), len(pred), len(attempts)),
              "on_camera": _prf(sum(1 for _, j in m if j in vis_idx), len(pred), len(vis_idx)),
              "ground": _prf(sum(1 for _, j in m if j in ground_idx), len(pred), len(ground_idx)),
              "completed": _prf(comp_tp, len(comp_pred), len(comp_true)),
              "outcome_correct": float(np.mean(outcome_ok)) if m else None,
              "team_correct": float(np.mean(team_ok)) if m else None,
              "players_correct": right_players / both_complete if both_complete else None,
              "speed_mae_kmh": float(np.mean(spd)) if spd else None,
              "length_mae_m": float(np.mean(lng)) if lng else None,
              "missed": [{"t": attempts[j]["t"], "outcome": attempts[j]["outcome"], "height": q(j, "height"),
                          "on_camera": j in vis_idx} for j in range(len(attempts)) if j not in {b for _, b in m}],
              "matched": [{"t": pred[i]["t"], "true_t": attempts[j]["t"], "team": attempts[j]["team_id"],
                           "completed": pred[i]["completed"], "true_outcome": attempts[j]["outcome"],
                           "passer": attempts[j]["player_id"], "receiver": attempts[j]["receiver_id"],
                           "speed_kmh": pred[i]["speed_kmh"], "true_speed_kmh": q(j, "speed_kmh"),
                           "length_m": pred[i]["length_m"], "true_length_m": q(j, "length_m")} for i, j in m]}

    # 4. shots
    true_shots = [e for e in clip["events"] if e["type"] == "shot" and t0 <= e["t"] <= t1 - 0.5]
    ms = _match_times([s["t"] for s in events["shots"]], [e["t"] for e in true_shots], tol=1.0)
    shot_err = [abs(events["shots"][i]["speed_kmh"] - true_shots[j]["qualifiers"]["speed_kmh"]) for i, j in ms]
    shots = {**_prf(len(ms), len(events["shots"]), len(true_shots)),
             "speed_abs_error_kmh": float(np.mean(shot_err)) if shot_err else None,
             "detected": [{"t": events["shots"][i]["t"], "speed_kmh": events["shots"][i]["speed_kmh"],
                           "true_speed_kmh": true_shots[j]["qualifiers"]["speed_kmh"]} for i, j in ms]}

    # 5. player top speeds (only frames where the player is on screen count for the truth)
    per_gt: dict[str, list[float]] = defaultdict(list)
    for tid, info in events["players"].items():
        g = track_gt.get(tid)
        if g is not None and info["seen_s"] >= 3:
            per_gt[g].append(info["top_speed_kmh"])
    speed_rows = []
    for g, ests in per_gt.items():
        true_top = max((gt_pos[k][g][2] for k, f in enumerate(frames) if g in f["boxes"] and g in gt_pos[k]),
                       default=None)
        if true_top:
            speed_rows.append({"player_id": g, "estimate_kmh": round(max(ests), 1), "true_kmh": round(true_top, 1)})
    top_err = [abs(r["estimate_kmh"] - r["true_kmh"]) for r in speed_rows]

    return {
        "detection": detection,
        "localisation": {"mean_m": float(np.mean(loc_err)) if loc_err else None,
                         "p90_m": float(np.quantile(loc_err, 0.9)) if loc_err else None},
        "teams": {"accuracy": team_acc},
        "identity": {"accuracy": id_acc, "tracks": len(long_tracks), "players_seen": len(seen_players)},
        "ball": ball_metrics,
        "passes": passes,
        "shots": shots,
        "player_speed": {"players": len(speed_rows),
                         "top_speed_mae_kmh": float(np.mean(top_err)) if top_err else None,
                         "rows": sorted(speed_rows, key=lambda r: -r["true_kmh"])},
    }
