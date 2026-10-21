"""Find players and the ball in broadcast frames.

Players: a COCO-pretrained Faster R-CNN (torchvision, BSD-3 licence) - the "person" class, unchanged, no fine-tuning
on our renders. Ball: at broadcast distance the ball is ~10 px, below what COCO detectors find reliably, so it gets a
classical detector (bright, round, compact blobs), with the candidates disambiguated by the tracker in track.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

PITCH_SPOTS = [(11.0, 34.0), (94.0, 34.0), (52.5, 34.0)]  # penalty spots and centre spot look like a ball


@dataclass
class Box:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float

    @property
    def foot(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, self.y2

    def as_list(self) -> list[float]:
        return [round(self.x1, 1), round(self.y1, 1), round(self.x2, 1), round(self.y2, 1), round(self.score, 3)]


class PlayerDetector:
    """torchvision Faster R-CNN (MobileNetV3-Large FPN), COCO weights, class 1 = person."""

    def __init__(self, score: float = 0.5, model: str = "mobilenet"):
        import torch
        from torchvision.models import detection as D

        torch.set_grad_enabled(False)
        if model == "resnet50":
            weights = D.FasterRCNN_ResNet50_FPN_V2_Weights.DEFAULT
            self.model = D.fasterrcnn_resnet50_fpn_v2(weights=weights, box_score_thresh=score)
        else:
            weights = D.FasterRCNN_MobileNet_V3_Large_FPN_Weights.DEFAULT
            self.model = D.fasterrcnn_mobilenet_v3_large_fpn(weights=weights, box_score_thresh=score)
        self.model.eval()
        self.preprocess = weights.transforms()
        self.name = self.describe(model)
        self._torch = torch

    @staticmethod
    def describe(model: str) -> str:
        return f"Faster R-CNN {'ResNet-50 FPN v2' if model == 'resnet50' else 'MobileNetV3-Large FPN'} (COCO)"

    def __call__(self, rgb: np.ndarray) -> list[Box]:
        x = self.preprocess(self._torch.from_numpy(rgb).permute(2, 0, 1))
        with self._torch.inference_mode():
            out = self.model([x])[0]
        boxes = []
        for (x1, y1, x2, y2), label, s in zip(out["boxes"].tolist(), out["labels"].tolist(), out["scores"].tolist()):
            if label == 1 and (y2 - y1) > 8:
                boxes.append(Box(x1, y1, x2, y2, s))
        return dedupe(boxes)


def dedupe(boxes: list[Box], contained: float = 0.6) -> list[Box]:
    """Drop partial boxes (half a body) that sit mostly inside a higher-scoring box; NMS keeps those at IoU < 0.5."""
    keep: list[Box] = []
    for b in sorted(boxes, key=lambda b: -b.score):
        area = (b.x2 - b.x1) * (b.y2 - b.y1)
        inside = False
        for k in keep:
            ix = max(0.0, min(b.x2, k.x2) - max(b.x1, k.x1))
            iy = max(0.0, min(b.y2, k.y2) - max(b.y1, k.y1))
            if ix * iy > contained * area:
                inside = True
                break
        if not inside:
            keep.append(b)
    return keep


def to_pitch(H: np.ndarray, u: float, v: float) -> tuple[float, float]:
    """Pixel -> pitch metres through the inverse of the camera's ground-plane homography."""
    p = np.linalg.solve(H, np.array([u, v, 1.0]))
    return float(p[0] / p[2]), float(p[1] / p[2])


def ball_candidates(rgb: np.ndarray, H: np.ndarray, people: list[Box]) -> list[tuple[float, float, float]]:
    """Bright, round, compact blobs that are not shorts, pitch spots or off the pitch: (u, v, score)."""
    import cv2

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    mask = ((hsv[..., 2] > 185) & (hsv[..., 1] < 70)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))  # lines
    n, _, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        _x, y, w, h, area = stats[i]
        if not (12 <= area <= 260) or max(w, h) > 2.2 * min(w, h):
            continue
        fill = area / float(w * h)
        if fill < 0.55:
            continue
        u = float(cents[i][0])
        v = float(y + h - 0.5)  # bottom of the ball = where it touches the grass (its centre is 0.3 m up)
        px, py = to_pitch(H, u, v)
        if not (-2 <= px <= 107 and -2 <= py <= 70):
            continue
        if any(abs(px - sx) < 0.8 and abs(py - sy) < 0.8 for sx, sy in PITCH_SPOTS):
            continue
        shorts = False
        for b in people:
            hgt = b.y2 - b.y1
            if b.x1 - 1 <= u <= b.x2 + 1 and b.y1 + 0.2 * hgt <= v <= b.y1 + 0.78 * hgt:
                shorts = True
                break
        if shorts:
            continue
        roundness = min(w, h) / max(w, h)
        out.append((float(u), float(v), float(fill * roundness)))
    return out
