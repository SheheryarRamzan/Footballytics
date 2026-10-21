"""Auto-eventing end to end: simulate -> render broadcast video -> detect -> track -> infer events -> score.

    python -m footballytics.vision.autoevent --matchday 9 --match HBC-KGA --seconds 45
    python -m footballytics.vision.autoevent --reuse          # re-score cached render + detections

Writes data/generated/autoevent/<match>/ (frames, broadcast.mp4, annotated.mp4, results.json) and, unless
--no-publish, the summary the app shows (seed/autoevent_latest.json), docs/AUTO_EVENTING.md and the annotated frame.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from ..sim.matchday import DATA_DIR
from .clip import busiest_window, make_clip
from .detect import Box, PlayerDetector, ball_candidates
from .evaluate import evaluate
from .events import infer_events, positions_at
from .render import encode_mp4, render_clip
from .track import Detection, assign_teams, ball_path, fill_gaps, track_players

ROOT = Path(__file__).resolve().parents[3]
SEED = Path(__file__).resolve().parents[1] / "seed" / "autoevent_latest.json"
REPORT = ROOT / "docs" / "AUTO_EVENTING.md"
IMAGE = ROOT / "docs" / "images" / "auto-eventing.png"
PUBLIC_IMAGE = ROOT / "frontend" / "public" / "auto-eventing.jpg"


def _rgb(path: Path) -> np.ndarray:
    import cv2

    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


BALL_VERSION = 2  # bump when ball_candidates changes: cached player boxes are kept, ball candidates recomputed
ROI_VERSION = 1  # bump when the zoomed re-detection around the ball changes
ROI_HALF = (238, 170, 102)  # half-width, height above and below the ball (pixels) of the zoomed window


def _roi_window(H: np.ndarray, ball: tuple[float, float], w: int, h: int) -> tuple[int, int, int, int]:
    p = H @ np.array([ball[0], ball[1], 1.0])
    u, v = p[0] / p[2], p[1] / p[2]
    hw, up, down = ROI_HALF
    return int(max(0, u - hw)), int(max(0, v - up)), int(min(w, u + hw)), int(min(h, v + down))


def _merge(full: list[Box], roi: list[Box], win: list[int] | None, margin: int = 12) -> list[Box]:
    """Zoomed boxes replace full-frame ones inside the window (minus a margin where crops cut players)."""
    from .detect import dedupe

    if not win:
        return full
    x1, y1, x2, y2 = win[0] + margin, win[1] + margin, win[2] - margin, win[3] - margin
    inside = lambda b: x1 <= (b.x1 + b.x2) / 2 <= x2 and y1 <= b.y2 <= y2
    return dedupe([b for b in full if not inside(b)] + [b for b in roi if inside(b)])


def detect_all(out: Path, render: dict, stride: int, model: str, reuse: bool) -> tuple[list[Detection], list, float]:
    """Players every ``stride`` frames (full frame, then a 2x zoomed window around the ball), ball every frame.

    Cached in detections.json; each stage is recomputed only when its version changes.
    """
    from .detect import to_pitch
    from .track import ball_path, detections_for_frame, fill_gaps

    cache = out / "detections.json"
    frames = render["frames"]
    fps, w, h = render["fps"], render["width"], render["height"]
    det_frames = list(range(0, len(frames), stride))
    c = json.loads(cache.read_text(encoding="utf-8")) if reuse and cache.exists() else {}
    same = c.get("stride") == stride and c.get("model") == model
    detector = None

    def get_detector() -> PlayerDetector:
        nonlocal detector
        detector = detector or PlayerDetector(model=model)
        return detector

    # 1. full-frame players
    if same and "boxes" in c:
        boxes_at = {int(k): [Box(*b) for b in bs] for k, bs in c["boxes"].items()}
        spf = c["seconds_per_frame"]
    else:
        boxes_at = {}
        t0 = time.time()
        for n, k in enumerate(det_frames):
            boxes_at[k] = get_detector()(_rgb(out / "frames" / f"{k:06d}.jpg"))
            if n % 50 == 0:
                print(f"  detected {n}/{len(det_frames)}", flush=True)
        spf = (time.time() - t0) / max(1, len(det_frames))
        c = {}
    # 2. ball candidates, every frame
    if c.get("ball_version") == BALL_VERSION:
        ball = [[tuple(x) for x in cs] for cs in c["ball"]]
    else:
        ball = [ball_candidates(_rgb(out / "frames" / f"{k:06d}.jpg"), np.array(f["H"]), boxes_at[k - k % stride])
                for k, f in enumerate(frames)]
    # 3. a first ball path, from full-frame players
    Hs = [np.array(f["H"]) for f in frames]
    feet = {k: [to_pitch(Hs[k], *b.foot) for b in bs] for k, bs in boxes_at.items()}
    path = fill_gaps(ball_path(ball, Hs, fps, [feet[k - k % stride] for k in range(len(frames))]), int(0.5 * fps))
    # 4. zoomed re-detection around the ball: separates players a full-frame pass merges in duels
    if same and c.get("roi_version") == ROI_VERSION:
        roi = {int(k): v for k, v in c["roi"].items()}
        roi_spf = c.get("roi_seconds_per_frame", 0.0)
    else:
        import cv2

        roi = {}
        t0 = time.time()
        for n, k in enumerate(det_frames):
            near = next((path[j] for j in (k, k - 1, k + 1, k - 2, k + 2) if 0 <= j < len(path) and path[j]), None)
            if near is None:
                continue
            x1, y1, x2, y2 = _roi_window(Hs[k], near, w, h)
            if x2 - x1 < 40 or y2 - y1 < 40:
                continue
            crop = cv2.resize(_rgb(out / "frames" / f"{k:06d}.jpg")[y1:y2, x1:x2], None, fx=2, fy=2,
                              interpolation=cv2.INTER_CUBIC)
            zb = [Box(x1 + b.x1 / 2, y1 + b.y1 / 2, x1 + b.x2 / 2, y1 + b.y2 / 2, b.score)
                  for b in get_detector()(crop)]
            roi[k] = {"window": [x1, y1, x2, y2], "boxes": [b.as_list() for b in zb]}
            if n % 50 == 0:
                print(f"  zoomed {n}/{len(det_frames)}", flush=True)
        roi_spf = (time.time() - t0) / max(1, len(roi))
    # 5. merged boxes -> pitch detections with shirt colours
    dets: list[Detection] = []
    for k in det_frames:
        r = roi.get(k)
        merged = _merge(boxes_at[k], [Box(*b) for b in r["boxes"]] if r else [], r["window"] if r else None)
        dets += detections_for_frame(k, frames[k]["t"], _rgb(out / "frames" / f"{k:06d}.jpg"), Hs[k], merged)
    cache.write_text(json.dumps({
        "stride": stride, "model": model, "seconds_per_frame": spf, "roi_seconds_per_frame": roi_spf,
        "detector": PlayerDetector.describe(model), "ball_version": BALL_VERSION, "roi_version": ROI_VERSION,
        "boxes": {str(k): [b.as_list() for b in bs] for k, bs in boxes_at.items()},
        "roi": {str(k): v for k, v in roi.items()}, "ball": ball}), encoding="utf-8")
    return dets, ball, spf + roi_spf * len(roi) / max(1, len(det_frames))


def annotate(out: Path, clip: dict, render: dict, dets: list[Detection], ball: list, events: dict,
             team_bgr: list[tuple[int, int, int]], stride: int) -> Path:
    """Draw what the pipeline saw: team-coloured boxes, the tracked ball, an event ticker and a pitch minimap."""
    import cv2

    frames = render["frames"]
    fps = render["fps"]
    by_k: dict[int, list[Detection]] = {}
    for d in dets:
        by_k.setdefault(d.k, []).append(d)
    adir = out / "annotated"
    adir.mkdir(exist_ok=True)
    feed = sorted([("PASS", p) for p in events["passes"]] + [("SHOT", s) for s in events["shots"]]
                  + [("INTERCEPTED", p) for p in events["turnovers"]], key=lambda e: e[1]["t"])
    for k, f in enumerate(frames):
        img = cv2.imread(str(out / "frames" / f"{k:06d}.jpg"))
        H = np.array(f["H"])
        dk = by_k.get(k - (k % stride), [])
        for d in dk:
            c = (0, 215, 255) if d.keeper else team_bgr[d.team]
            b = d.box
            cv2.rectangle(img, (int(b.x1), int(b.y1)), (int(b.x2), int(b.y2)), c, 2)
            cv2.putText(img, str(d.track), (int(b.x1), int(b.y1) - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.38, c, 1,
                        cv2.LINE_AA)
        if ball[k] is not None:
            p = H @ np.array([ball[k][0], ball[k][1], 1.0])
            u, v = int(p[0] / p[2]), int(p[1] / p[2]) - 5  # contact point -> centre of the ball
            cv2.circle(img, (u, v), 10, (255, 255, 255), 2, cv2.LINE_AA)
            moving = next((e for _, e in feed if e["t"] <= f["t"] <= e.get("t_end", e["t"] + 0.6)), None)
            if moving and moving["speed_kmh"]:
                cv2.putText(img, f"{moving['speed_kmh']:.0f} km/h", (u + 13, v - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                            (255, 255, 255), 1, cv2.LINE_AA)
        # HUD
        t = f["t"]
        done = [e for e in feed if e[1]["t"] <= t]
        cv2.rectangle(img, (14, 14), (430, 96), (22, 15, 7), -1)
        cv2.putText(img, "AUTO-EVENTING  video -> events", (26, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (166, 211, 34), 2, cv2.LINE_AA)
        n_pass = sum(1 for kind, _ in done if kind == "PASS")
        n_int = sum(1 for kind, _ in done if kind == "INTERCEPTED")
        n_shot = sum(1 for kind, _ in done if kind == "SHOT")
        cv2.putText(img, f"passes {n_pass}   intercepted {n_int}   shots {n_shot}",
                    (26, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 236, 246), 1, cv2.LINE_AA)
        if done and t - done[-1][1]["t"] < 2.5:
            kind, e = done[-1]
            label = (f"{kind}  {e['speed_kmh']:.0f} km/h" if kind == "SHOT"
                     else f"{kind}  {e.get('length_m', 0):.0f} m  {e['speed_kmh'] or 0:.0f} km/h")
            cv2.putText(img, label, (26, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (36, 191, 251), 1, cv2.LINE_AA)
        # minimap
        mw, mh, mx, my = 210, 136, img.shape[1] - 226, img.shape[0] - 152
        cv2.rectangle(img, (mx - 4, my - 4), (mx + mw + 4, my + mh + 4), (22, 15, 7), -1)
        cv2.rectangle(img, (mx, my), (mx + mw, my + mh), (60, 120, 60), 1)
        cv2.line(img, (mx + mw // 2, my), (mx + mw // 2, my + mh), (60, 120, 60), 1)
        for d in dk:
            c = (0, 215, 255) if d.keeper else team_bgr[d.team]
            cv2.circle(img, (int(mx + d.x / 105 * mw), int(my + d.y / 68 * mh)), 3, c, -1)
        if ball[k] is not None:
            cv2.circle(img, (int(mx + ball[k][0] / 105 * mw), int(my + ball[k][1] / 68 * mh)), 3, (255, 255, 255), -1)
        cv2.imwrite(str(adir / f"{k:06d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    path = out / "annotated.mp4"
    encode_mp4(adir, path, fps)
    return path


def run(matchday: int = 9, match: str = "HBC-KGA", seconds: float = 45.0, start: float | None = None,
        stride: int = 2, model: str = "mobilenet", reuse: bool = False, publish: bool = True,
        width: int = 1280, height: int = 720, out: Path | None = None) -> dict:
    import cv2

    began = time.time()
    out = Path(out or DATA_DIR / "autoevent" / f"md{matchday:02d}-{match}")
    out.mkdir(parents=True, exist_ok=True)
    clip_path = out / "clip.json"
    if reuse and clip_path.exists():
        clip = json.loads(clip_path.read_text(encoding="utf-8"))
    else:
        if start is None:
            start = busiest_window(matchday, match, seconds)
            print(f"busiest {seconds:.0f}s window starts at {start:.0f}s of play")
        clip = make_clip(matchday, match, start, seconds)
        clip_path.write_text(json.dumps(clip), encoding="utf-8")
    render_path = out / "render.json"
    if reuse and render_path.exists():
        render = json.loads(render_path.read_text(encoding="utf-8"))
    else:
        print(f"rendering {len(clip['video'])} frames ...")
        render = render_clip(clip, out, width, height)
    fps = render["fps"]
    frames = render["frames"]
    print("detecting ...")
    dets, cands, spf = detect_all(out, render, stride, model, reuse)

    teams = assign_teams(dets)
    tracks = track_players(dets, fps)
    pos = positions_at(tracks, len(frames), max_gap=int(0.6 * fps))
    players_at = [[p[k] for p in pos.values() if p[k] is not None] for k in range(len(frames))]
    ball = fill_gaps(ball_path(cands, [np.array(f["H"]) for f in frames], fps, players_at), int(0.5 * fps))
    events = infer_events(tracks, ball, [f["t"] for f in frames], fps, stride, dets)
    metrics = evaluate(clip, render, dets, tracks, ball, events, list(range(0, len(frames), stride)))

    lab = np.array(teams["centers"], dtype=np.uint8).reshape(1, 2, 3)
    team_bgr = [tuple(int(c) for c in px) for px in cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)[0]]
    print("annotating ...")
    annotated = annotate(out, clip, render, dets, ball, events, team_bgr, stride)

    m = clip["meta"]
    result = {
        "meta": {"name": f"autoevent-{m['match_id']}-{datetime.now():%Y%m%d-%H%M%S}", "match_id": m["match_id"],
                 "home": m["home_name"], "away": m["away_name"], "start_t": m["start_t"], "seconds": m["seconds"],
                 "fps": fps, "frames": len(frames), "resolution": f"{render['width']}x{render['height']}",
                 "detector": f"Faster R-CNN {'ResNet-50 FPN v2' if model == 'resnet50' else 'MobileNetV3-Large FPN'}"
                             " (torchvision, COCO weights, no fine-tuning)",
                 "detector_hz": fps / stride, "detector_s_per_frame": round(spf, 2),
                 "render_s_per_frame": render.get("seconds_per_frame", 0.43),
                 "full_run_min": round((len(frames) * render.get("seconds_per_frame", 0.43)
                                        + len(frames) / stride * spf) / 60, 1),
                 "runtime_s": round(time.time() - began, 1), "created": datetime.now().isoformat(timespec="seconds")},
        "metrics": metrics,
        "detected": {"passes": events["passes"], "turnovers": events["turnovers"], "shots": events["shots"],
                     "players": {str(k): v for k, v in events["players"].items()}},
        "truth": {"passes": sum(1 for e in clip["events"] if e["type"] in ("pass", "cross")),
                  "shots": sum(1 for e in clip["events"] if e["type"] == "shot")},
        "video": {"broadcast": str(out / "broadcast.mp4"), "annotated": str(annotated)},
    }
    (out / "results.json").write_text(json.dumps(result, indent=2, default=float), encoding="utf-8")
    if publish:
        publish_results(result, out, events)
    return result


def _best_frame(result: dict, frames_dir: Path, fps: int, start_t: float) -> Path:
    """A representative annotated frame for the README and the Studio: mid-flight of a cleanly measured pass."""
    files = sorted(frames_dir.glob("*.jpg"))
    found = [m for m in result["metrics"]["passes"]["matched"] if m["completed"] and m["true_speed_kmh"]]
    if found:
        m = min(found, key=lambda m: abs(m["speed_kmh"] - m["true_speed_kmh"]) - 0.1 * min(m["length_m"], 20))
        k = int((m["t"] - start_t + 0.3) * fps)
    else:
        k = len(files) // 2
    return files[max(0, min(k, len(files) - 1))]


def publish_results(result: dict, out: Path, events: dict) -> None:
    import cv2

    met = result["metrics"]
    summary = {"meta": result["meta"], "metrics": {k: v for k, v in met.items() if k not in ("passes",)},
               "passes": {k: v for k, v in met["passes"].items() if k != "matched"},
               "examples": met["passes"]["matched"][:6], "shots": met["shots"].get("detected", [])}
    summary["metrics"]["player_speed"] = {**met["player_speed"], "rows": met["player_speed"]["rows"][:8]}
    SEED.write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    frame = _best_frame(result, out / "annotated", result["meta"]["fps"], result["meta"]["start_t"])
    img = cv2.imread(str(frame))
    IMAGE.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(IMAGE), img)
    PUBLIC_IMAGE.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(PUBLIC_IMAGE), cv2.resize(img, (640, 360)), [cv2.IMWRITE_JPEG_QUALITY, 85])
    REPORT.write_text(report_markdown(result), encoding="utf-8")
    print("published", SEED.name, IMAGE.name, REPORT.name)


def _pct(v) -> str:
    return "–" if v is None else f"{v * 100:.0f}%"


def _num(v, unit: str = "", d: int = 1) -> str:
    return "–" if v is None else f"{v:.{d}f}{unit}"


def report_markdown(r: dict) -> str:
    m, x = r["meta"], r["metrics"]
    pa, sh, sp = x["passes"], x["shots"], x["player_speed"]
    lines = [
        "# Auto-eventing: broadcast video → events",
        "",
        (f"Run `{m['name']}`: {m['seconds']:.0f} s of {m['home']} v {m['away']} (`{m['match_id']}`, from "
        f"{m['start_t'] / 60:.1f} min of play), {m['frames']} frames at {m['fps']} fps, {m['resolution']}."),
        "",
        ("The video is rendered by the app's own 3D broadcast renderer from simulator tracking. The pipeline sees only "
        "the pixels and the camera calibration. The simulator's events and tracking are the answer key it is "
        "scored against."),
        "",
        ("![Annotated broadcast frame: team-coloured player boxes with track ids, the tracked ball, the event ticker "
        "and a pitch minimap](images/auto-eventing.png)"),
        "",
        "## Pipeline",
        "",
        "| Stage | Method |",
        "|---|---|",
        (f"| Players | {m['detector']}, person class, every {r['meta']['fps'] / m['detector_hz']:.0f} frames "
         f"({m['detector_hz']:.1f} Hz), then again on a 2x zoomed window around the ball, where duels merge "
         f"players ({m['detector_s_per_frame']} s per frame on CPU for both) |"),
        ("| Ball | Classical detector (bright, round, compact blobs; shorts and pitch spots rejected), then the most "
         "plausible path through all frames' candidates (dynamic programming, bridges occlusions) |"),
        "| Pitch coordinates | Foot point through the broadcast camera's ground-plane homography (calibration) |",
        "| Teams | k-means on shirt colour (two teams + keepers), no kit colours given |",
        "| Tracking | Hungarian assignment with constant-velocity prediction; shirt colour as a soft cost |",
        ("| Events | A flight = the ball moving faster than a dribble; from a player to a team-mate (median speed "
         "above 32 km/h) is a pass, to an opponent an interception; passer = who received the last ball "
         "(possession continuity); shot = struck above 50 km/h within 30 m, heading for the goal mouth |"),
        ("| Speeds | Smoothed track and ball positions → player top speed, sprints (≥ 25.2 km/h), ball and shot "
        "speed |"),
        "",
        "## Results against the answer key",
        "",
        "| Metric | Result |",
        "|---|---|",
        (f"| Player detection (IoU ≥ 0.5) | precision {_pct(x['detection']['precision'])}, recall "
        f"{_pct(x['detection']['recall'])} |"),
        (f"| Position on the pitch | mean error {_num(x['localisation']['mean_m'], ' m', 2)}, "
        f"90th percentile {_num(x['localisation']['p90_m'], ' m', 2)} |"),
        f"| Team assignment | {_pct(x['teams']['accuracy'])} correct |",
        (f"| Identity (track → player) | {_pct(x['identity']['accuracy'])} of detections on the right track; "
        f"{x['identity']['tracks']} tracks for {x['identity']['players_seen']} players seen |"),
        (f"| Ball | tracked in {_pct(x['ball']['tracked_share'])} of frames where it is on screen; "
        f"{_pct(x['ball']['within_2m_share'])} of those within 2 m (median error "
        f"{_num(x['ball']['median_error_m'], ' m', 2)}) |"),
        (f"| Pass attempts found (±1 s) | {pa['attempts']['tp']} of {pa['attempts']['true']} "
         f"(recall {_pct(pa['attempts']['recall'])}, precision {_pct(pa['attempts']['precision'])}); passes along "
         f"the ground {pa['ground']['tp']} of {pa['ground']['true']} |"),
        (f"| Outcome (completed vs intercepted) / passing team | {_pct(pa['outcome_correct'])} / "
         f"{_pct(pa['team_correct'])} correct for the attempts found |"),
        (f"| Completed passes | precision {_pct(pa['completed']['precision'])}, recall "
         f"{_pct(pa['completed']['recall'])}; passer and receiver both identified in "
         f"{_pct(pa['players_correct'])} |"),
        f"| Pass speed / length | mean error {_num(pa['speed_mae_kmh'], ' km/h')} / {_num(pa['length_mae_m'], ' m')} |",
        (f"| Shots | {sh['tp']} of {sh['true']} found, {sh['predicted']} predicted; speed error "
        f"{_num(sh['speed_abs_error_kmh'], ' km/h')} |"),
        f"| Player top speed | mean error {_num(sp['top_speed_mae_kmh'], ' km/h')} over {sp['players']} players |",
        "",
        "## Limits",
        "",
        ("- The renders are stylised: no motion blur, crowd noise or broadcast graphics. Real footage would need "
        "fine-tuned detectors."),
        "- The camera calibration comes from the renderer. A real system would estimate it from the pitch lines.",
        ("- The ball's position comes from the ground plane, so lofted balls are placed where their shadow would be. "
        "That error shows up in the ball and pass-length numbers."),
        "- A pass or shot off camera cannot be seen, which is why on-camera recall is reported separately.",
        ("- A blocked shot travels a few metres and looks like any other short kick. When a marker stands between "
         "the camera and the passer, possession continuity, not the pixels, names the passing team."),
        "- Identity is kept by tracking alone. Shirt numbers are too small to read at broadcast distance.",
        "",
        "## Run it",
        "",
        "```bash",
        "cd frontend && npm run build          # the offline renderer is frontend/render.html",
        'cd ../backend && .venv/Scripts/pip install -e ".[vision,evals]"',
        ".venv/Scripts/python -m footballytics.vision.autoevent --matchday 9 --match HBC-KGA --seconds 45",
        "```",
        "",
        (f"A full run takes about {m['full_run_min']:.0f} min on a laptop CPU (rendering "
         f"{m['render_s_per_frame']} s per frame, detection {m['detector_s_per_frame']} s per detector frame; "
         "tracking and scoring take seconds). Outputs go to `backend/data/generated/autoevent/` (broadcast.mp4, "
         "annotated.mp4, results.json)."),
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Auto-eventing: broadcast video -> events, scored against ground truth")
    ap.add_argument("--matchday", type=int, default=9)
    ap.add_argument("--match", default="HBC-KGA")
    ap.add_argument("--seconds", type=float, default=45.0)
    ap.add_argument("--start", type=float, help="seconds of play; default: the busiest window of the match")
    ap.add_argument("--stride", type=int, default=2, help="run the player detector every N frames")
    ap.add_argument("--model", choices=["mobilenet", "resnet50"], default="mobilenet")
    ap.add_argument("--reuse", action="store_true", help="reuse the cached clip, render and detections")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--out", type=Path, help="working folder (default data/generated/autoevent/md<N>-<match>)")
    args = ap.parse_args()
    r = run(args.matchday, args.match, args.seconds, args.start, args.stride, args.model, args.reuse,
            not args.no_publish, out=args.out)
    x = r["metrics"]
    print(json.dumps({"detection": x["detection"],
                      "passes": {k: v for k, v in x["passes"].items() if k not in ("matched", "missed")},
                      "ball": x["ball"], "shots": {k: v for k, v in x["shots"].items() if k != "detected"},
                      "player_speed_mae": x["player_speed"]["top_speed_mae_kmh"], "teams": x["teams"],
                      "identity": x["identity"], "localisation": x["localisation"]}, indent=1, default=float))


if __name__ == "__main__":
    main()
