"""Render a clip as broadcast video with the app's own 3D renderer (frontend/render.html), headless.

Serves the built frontend from a local port, drives ``window.fbx`` with Playwright one frame at a time and writes:
  frames/000000.jpg ...   the video frames
  broadcast.mp4           the same frames as H.264 video
  render.json             per frame: camera homography (pitch metres -> pixels), true player boxes, true ball pixel
"""

from __future__ import annotations

import base64
import functools
import http.server
import json
import threading
import time
from pathlib import Path

import numpy as np

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"
BROWSER_ARGS = ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


def homography(ground: list[list[float]]) -> list[list[float]]:
    """Least-squares homography from pitch (x, y) to pixel (u, v) correspondences (DLT)."""
    rows = []
    for x, y, u, v in ground:
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, vt = np.linalg.svd(np.array(rows, dtype=float))
    h = vt[-1].reshape(3, 3)
    return (h / h[2, 2]).tolist()


def render_clip(clip: dict, out_dir: Path, width: int = 1280, height: int = 720, dist: Path = FRONTEND_DIST,
                progress: bool = True) -> dict:
    from playwright.sync_api import sync_playwright

    if not (dist / "render.html").exists():
        raise FileNotFoundError(f"{dist / 'render.html'} missing: run `npm run build` in frontend/")
    out_dir = Path(out_dir)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(dist)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fps = clip["meta"]["fps"]
    setup = {"width": width, "height": height,
             "players": [{k: p[k] for k in ("id", "number", "name", "shirt", "shorts", "socks", "gk")}
                         for p in clip["players"]]}
    meta: list[dict] = []
    began = time.time()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True, args=BROWSER_ARGS)
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/render.html")
            page.wait_for_function("window.fbx !== undefined")
            page.evaluate("s => window.fbx.setup(s)", setup)
            n = len(clip["video"])
            for i, f in enumerate(clip["video"]):
                out = page.evaluate("f => window.fbx.frame(f)", {"p": f["p"], "b": f["b"], "dt": 1 / fps})
                jpg = base64.b64decode(out["image"].split(",", 1)[1])
                (frames_dir / f"{i:06d}.jpg").write_bytes(jpg)
                meta.append({"t": f["t"], "H": homography(out["ground"]), "boxes": out["boxes"], "ball": out["ball"]})
                if progress and i % 100 == 0:
                    print(f"  rendered {i}/{n}", flush=True)
            browser.close()
    finally:
        server.shutdown()
    info = {"width": width, "height": height, "fps": fps, "frames": meta,
            "seconds_per_frame": round((time.time() - began) / max(1, len(meta)), 2)}
    (out_dir / "render.json").write_text(json.dumps(info), encoding="utf-8")
    encode_mp4(frames_dir, out_dir / "broadcast.mp4", fps)
    return info


def encode_mp4(frames_dir: Path, path: Path, fps: int) -> None:
    import imageio.v2 as imageio

    with imageio.get_writer(path, fps=fps, codec="libx264", quality=8, pixelformat="yuv420p",
                            macro_block_size=8) as w:
        for f in sorted(Path(frames_dir).glob("*.jpg")):
            w.append_data(imageio.imread(f))
