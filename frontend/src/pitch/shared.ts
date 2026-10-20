import { liveFrames } from "../store";

export const L = 105;
export const W = 68;

export interface Sample {
  players: Map<string, { x: number; y: number; kmh: number }>;
  ball: [number, number, number];
  owner: string | null;
  clock: number;
}

/** Interpolate between the last two tracking frames (one-frame latency, smooth at any frame rate). */
export function sample(now: number): Sample | null {
  const { prev, cur, prevAt, curAt } = liveFrames;
  if (!cur) return null;
  if (!prev) {
    return {
      players: new Map(cur.p.map(([id, x, y, k]) => [id, { x, y, kmh: k }])),
      ball: cur.b,
      owner: cur.o,
      clock: cur.c,
    };
  }
  const span = Math.max(16, curAt - prevAt);
  const a = Math.min(1, Math.max(0, (now - curAt) / span));
  const prevMap = new Map(prev.p.map((p) => [p[0], p]));
  const players = new Map<string, { x: number; y: number; kmh: number }>();
  for (const [id, x, y, k] of cur.p) {
    const p = prevMap.get(id);
    if (p && Math.hypot(p[1] - x, p[2] - y) < 8) {
      players.set(id, { x: p[1] + (x - p[1]) * a, y: p[2] + (y - p[2]) * a, kmh: k });
    } else {
      players.set(id, { x, y, kmh: k });
    }
  }
  const jump = Math.hypot(prev.b[0] - cur.b[0], prev.b[1] - cur.b[1]) > 15;
  const ball: [number, number, number] = jump
    ? cur.b
    : [prev.b[0] + (cur.b[0] - prev.b[0]) * a, prev.b[1] + (cur.b[1] - prev.b[1]) * a, prev.b[2] + (cur.b[2] - prev.b[2]) * a];
  return { players, ball, owner: cur.o, clock: prev.c + (cur.c - prev.c) * a };
}

/** Draw pitch markings in pitch metres onto a 2D context already scaled so 1 unit = 1 metre. */
export function drawMarkings(ctx: CanvasRenderingContext2D, lineWidth: number, color = "rgba(255,255,255,0.85)") {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.strokeRect(0, 0, L, W);
  ctx.beginPath();
  ctx.moveTo(L / 2, 0);
  ctx.lineTo(L / 2, W);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(L / 2, W / 2, 9.15, 0, Math.PI * 2);
  ctx.stroke();
  for (const side of [0, 1]) {
    const x0 = side === 0 ? 0 : L;
    const dir = side === 0 ? 1 : -1;
    ctx.strokeRect(side === 0 ? 0 : L - 16.5, W / 2 - 20.16, 16.5, 40.32);
    ctx.strokeRect(side === 0 ? 0 : L - 5.5, W / 2 - 9.16, 5.5, 18.32);
    ctx.beginPath();
    ctx.arc(x0 + dir * 11, W / 2, 9.15, side === 0 ? -0.927 : Math.PI - 0.927, side === 0 ? 0.927 : Math.PI + 0.927);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x0 + dir * 11, W / 2, lineWidth * 1.2, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
  }
  ctx.beginPath();
  ctx.arc(L / 2, W / 2, lineWidth * 1.4, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

export function drawGrass(ctx: CanvasRenderingContext2D, light = "#1f7a3e", dark = "#1a6d36") {
  const stripes = 18;
  for (let i = 0; i < stripes; i++) {
    ctx.fillStyle = i % 2 ? light : dark;
    ctx.fillRect((i * L) / stripes, 0, L / stripes + 0.05, W);
  }
}

export function contrastText(hex: string): string {
  const c = hex.replace("#", "");
  const r = parseInt(c.slice(0, 2), 16);
  const g = parseInt(c.slice(2, 4), 16);
  const b = parseInt(c.slice(4, 6), 16);
  return r * 0.299 + g * 0.587 + b * 0.114 > 150 ? "#0b1020" : "#ffffff";
}
