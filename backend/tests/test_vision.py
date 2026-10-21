"""Auto-eventing logic on synthetic inputs: calibration, ball path, tracking, event inference, scoring.

No detector or browser is involved (those are exercised by `python -m footballytics.vision.autoevent`).
"""

import numpy as np
import pytest

pytest.importorskip("scipy")

from footballytics.vision.clip import make_clip
from footballytics.vision.detect import Box, dedupe, to_pitch
from footballytics.vision.evaluate import _match_times, _prf
from footballytics.vision.events import flights, infer_events, smooth_speed
from footballytics.vision.render import homography
from footballytics.vision.track import Detection, Track, ball_path, fill_gaps, track_players

FPS = 25

H_TRUE = np.array([[12.0, 3.0, 100.0], [0.5, -6.0, 600.0], [0.001, 0.004, 1.0]])


def _project(x, y):
    p = H_TRUE @ [x, y, 1.0]
    return p[0] / p[2], p[1] / p[2]


def test_homography_from_correspondences_maps_pixels_back_to_the_pitch():
    ground = [[x, y, *_project(x, y)] for x in (0, 30, 60, 105) for y in (0, 20, 50, 68)]
    H = np.array(homography(ground))
    assert np.allclose(H / H[2, 2], H_TRUE / H_TRUE[2, 2], atol=1e-6)
    u, v = _project(41.3, 22.7)
    assert np.allclose(to_pitch(H, u, v), (41.3, 22.7), atol=1e-6)


def test_dedupe_drops_half_body_boxes_inside_a_better_one():
    full = Box(100, 100, 120, 160, 0.9)
    upper = Box(101, 100, 119, 130, 0.6)
    other = Box(140, 100, 160, 160, 0.8)
    assert dedupe([upper, full, other]) == [full, other]


def _ball_path_scene():
    """A player dribbles the ball along y=30 at 12 m/s; a white blob sits still 9 m away the whole time."""
    Hs = [np.eye(3)] * 50
    cands, truth = [], []
    for k in range(50):
        x = 20 + 12 * k / FPS
        truth.append(x)
        row = [(x, 30.0, 0.9), (40.0, 39.0, 0.95)]
        if k in (20, 21, 22):  # the ball is hidden behind a player for three frames
            row = row[1:]
        cands.append(row)
    players = [[(x - 0.6, 30.0)] for x in truth]
    return cands, Hs, players, truth


def test_ball_path_follows_the_moving_ball_not_the_static_blob_and_bridges_occlusion():
    cands, Hs, players, truth = _ball_path_scene()
    path = fill_gaps(ball_path(cands, Hs, FPS, players), 12)
    assert all(p is not None for p in path)
    assert max(abs(p[0] - x) for p, x in zip(path, truth)) < 0.3
    assert all(abs(p[1] - 30.0) < 0.3 for p in path)


def _det(k, x, y, team):
    return Detection(k, k / FPS, Box(0, 0, 1, 1, 1.0), x, y, np.zeros(3), team=team, shirt_team=team)


def test_tracking_keeps_two_players_apart_and_survives_a_missed_frame():
    dets = []
    for k in range(0, 40, 2):
        if k != 20:  # both missed once
            dets.append(_det(k, 10 + 0.2 * k, 20.0, 0))
            dets.append(_det(k, 10 + 0.2 * k, 26.0, 1))
    tracks = track_players(dets, FPS)
    assert len(tracks) == 2
    assert {t.team for t in tracks} == {0, 1}


def _pass_scene(receiver_team: int, kick_kmh: float):
    """Player A (team 0) at x=10 kicks along y=34 to player B at x=30, who then keeps it."""
    n, fps = 75, FPS
    speed = kick_kmh / 3.6
    ball, dets = [], []
    t_kick = 20
    for k in range(n):
        x = 10.0 if k < t_kick else min(30.0, 10.0 + speed * (k - t_kick) / fps)
        ball.append((x, 34.0))
        if k % 2 == 0:
            dets.append(_det(k, 9.4, 34.0, 0))
            dets.append(_det(k, 30.6, 34.0, receiver_team))
    tracks = track_players(dets, fps)
    times = [6000 + k / fps for k in range(n)]
    return infer_events(tracks, ball, times, fps, 2, dets), times[t_kick]


def test_a_struck_ball_to_a_teammate_is_a_pass_with_its_speed_and_length():
    ev, t_kick = _pass_scene(receiver_team=0, kick_kmh=50)
    assert len(ev["passes"]) == 1 and not ev["turnovers"]
    p = ev["passes"][0]
    assert abs(p["t"] - t_kick) < 0.2
    assert 17 <= p["length_m"] <= 21
    assert 44 <= p["speed_kmh"] <= 55


def test_the_same_ball_to_an_opponent_is_a_turnover_and_a_dribble_is_nothing():
    ev, _ = _pass_scene(receiver_team=1, kick_kmh=50)
    assert not ev["passes"] and len(ev["turnovers"]) == 1
    slow, _ = _pass_scene(receiver_team=0, kick_kmh=18)  # running pace: a dribble, never "in flight"
    assert not slow["passes"] and not slow["turnovers"]


def test_flights_and_speed_need_a_moving_ball():
    still = [(50.0, 34.0)] * 30
    assert flights(still, smooth_speed(still, FPS, 5), FPS) == []
    v = smooth_speed([(10 + k * 0.5, 34.0) for k in range(30)], FPS, 5)
    assert all(abs(s - 45.0) < 0.5 for s in v[3:-3] if s is not None)  # 0.5 m per frame at 25 fps


def test_event_matching_scores_precision_and_recall():
    m = _match_times([10.0, 12.1, 30.0], [10.4, 12.0, 20.0], tol=1.0)
    assert sorted(m) == [(0, 0), (1, 1)]
    s = _prf(len(m), 3, 3)
    assert s["precision"] == pytest.approx(2 / 3) and s["recall"] == pytest.approx(2 / 3)


def test_clip_is_the_answer_key_for_a_window_of_a_real_matchday_match():
    clip = make_clip(9, "HBC-KGA", start_s=120.0, seconds=2.0, fps=25)
    assert clip["meta"]["match_id"] == "md09-HBC-KGA"
    assert 50 <= len(clip["video"]) <= 56  # 2 s at 25 fps, plus a 0.1 s margin each side
    assert 20 <= len(clip["tracking"]) <= 23
    assert {p["side"] for p in clip["players"]} == {0, 1} and len(clip["players"]) == 22
    assert all(not any(k.startswith("_") for k in e["qualifiers"]) for e in clip["events"])  # public events only
    first = clip["video"][0]
    assert len(first["p"]) == 22 and len(first["b"]) == 3


def test_tracks_report_their_points():
    tr = Track(0, 1, {0: (1.0, 2.0), 4: (3.0, 2.0)})
    assert tr.last() == (4, (3.0, 2.0))
    assert tr.velocity(FPS) == pytest.approx((12.5, 0.0))
