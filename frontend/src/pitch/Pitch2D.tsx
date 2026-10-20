import { useEffect, useRef } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { L, W, contrastText, drawGrass, drawMarkings, sample } from "./shared";

/** A club colour that reads on dark grass: very dark primaries fall back to the secondary colour. */
function visibleColor(club: { primary: string; secondary: string } | undefined, fallback: string): string {
  if (!club) return fallback;
  const c = club.primary.replace("#", "");
  const lum = parseInt(c.slice(0, 2), 16) * 0.299 + parseInt(c.slice(2, 4), 16) * 0.587 + parseInt(c.slice(4, 6), 16) * 0.114;
  return lum < 45 ? club.secondary : club.primary;
}

/** Tactical top-down view: players, ball trail, squad highlights, pass arcs and (analyst) pitch control. */
export function Pitch2D({ showControl }: { showControl: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const controlRef = useRef<number[][] | null>(null);
  const stage = useStore((s) => s.stage);

  useEffect(() => {
    if (!showControl || !stage) {
      controlRef.current = null;
      return;
    }
    let alive = true;
    const poll = async () => {
      try {
        const pc = await api.pitchControl(stage);
        if (alive) controlRef.current = pc.grid_full;
      } catch {
        /* match not started yet */
      }
    };
    poll();
    const id = window.setInterval(poll, 1500);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [showControl, stage]);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d")!;
    let raf = 0;
    const trail: [number, number][] = [];
    let lastTrail = 0;

    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      if (canvas.width !== Math.round(rect.width * dpr) || canvas.height !== Math.round(rect.height * dpr)) {
        canvas.width = Math.round(rect.width * dpr);
        canvas.height = Math.round(rect.height * dpr);
      }
      const pad = 3;
      const scale = Math.min(canvas.width / (L + pad * 2), canvas.height / (W + pad * 2));
      const ox = (canvas.width - L * scale) / 2;
      const oy = (canvas.height - W * scale) / 2;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = "#0b2a17";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      // pitch metres -> canvas, y flipped so y=68 is the top touchline
      ctx.setTransform(scale, 0, 0, -scale, ox, oy + W * scale);
      drawGrass(ctx);

      const grid = controlRef.current;
      if (grid) {
        const ny = grid.length;
        const nx = grid[0].length;
        const { clubs, matches } = useStore.getState();
        const m = matches[useStore.getState().stage ?? ""];
        const hc = visibleColor(clubs[m?.home ?? ""], "#3b82f6");
        const ac = visibleColor(clubs[m?.away ?? ""], "#ef4444");
        for (let j = 0; j < ny; j++)
          for (let i = 0; i < nx; i++) {
            const p = grid[j][i];
            const strength = Math.abs(p - 0.5) * 2;
            ctx.globalAlpha = 0.08 + strength * 0.38;
            ctx.fillStyle = p > 0.5 ? hc : ac;
            ctx.fillRect((i * L) / nx, (j * W) / ny, L / nx + 0.05, W / ny + 0.05);
          }
        ctx.globalAlpha = 1;
      }
      drawMarkings(ctx, 0.28);

      const s = sample(now);
      if (!s) return;
      const { players, clubs, fan, overlays } = useStore.getState();
      const squad = new Set(fan?.squad ?? []);

      // Pass arcs for active line-breaking pass overlays
      for (const o of overlays) {
        if (o.template !== "pass_arc" || o.until < now) continue;
        const f = o.moment.facts;
        if (!f.start || !f.end) continue;
        ctx.strokeStyle = "#fde047";
        ctx.lineWidth = 0.5;
        ctx.setLineDash([1.6, 1]);
        ctx.beginPath();
        ctx.moveTo(f.start[0], f.start[1]);
        const mx = (f.start[0] + f.end[0]) / 2;
        const my = (f.start[1] + f.end[1]) / 2 + 4;
        ctx.quadraticCurveTo(mx, my, f.end[0], f.end[1]);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      if (now - lastTrail > 60) {
        trail.push([s.ball[0], s.ball[1]]);
        if (trail.length > 40) trail.shift();
        lastTrail = now;
      }
      ctx.lineWidth = 0.35;
      for (let i = 1; i < trail.length; i++) {
        ctx.strokeStyle = `rgba(255,255,255,${(i / trail.length) * 0.5})`;
        ctx.beginPath();
        ctx.moveTo(trail[i - 1][0], trail[i - 1][1]);
        ctx.lineTo(trail[i][0], trail[i][1]);
        ctx.stroke();
      }

      // Players
      for (const [id, p] of s.players) {
        const pl = players[id];
        const club = pl ? clubs[pl.club_id] : undefined;
        const fill = pl?.group === "GK" ? "#facc15" : club?.primary ?? "#888";
        const r = 1.25;
        if (squad.has(id)) {
          ctx.beginPath();
          ctx.arc(p.x, p.y, r + 0.75, 0, Math.PI * 2);
          ctx.strokeStyle = id === fan?.captain ? "#fbbf24" : "rgba(251,191,36,0.75)";
          ctx.lineWidth = id === fan?.captain ? 0.55 : 0.35;
          ctx.stroke();
        }
        ctx.beginPath();
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fillStyle = fill;
        ctx.fill();
        ctx.lineWidth = 0.22;
        ctx.strokeStyle = club?.secondary ?? "#fff";
        ctx.stroke();
        // number (un-flip text)
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.scale(1, -1);
        ctx.fillStyle = contrastText(fill);
        ctx.font = "bold 1.2px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(pl?.number ?? ""), 0, 0.08);
        if (squad.has(id) || id === s.owner) {
          ctx.font = "600 1.25px system-ui, sans-serif";
          ctx.fillStyle = "rgba(255,255,255,0.95)";
          ctx.fillText(pl?.short_name ?? id, 0, -2.4);
        }
        ctx.restore();
      }
      // Ball (shadow + ball raised by height)
      ctx.beginPath();
      ctx.arc(s.ball[0], s.ball[1], 0.55, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(0,0,0,0.35)";
      ctx.fill();
      ctx.beginPath();
      ctx.arc(s.ball[0] + s.ball[2] * 0.15, s.ball[1] + s.ball[2] * 0.3, 0.6 + s.ball[2] * 0.04, 0, Math.PI * 2);
      ctx.fillStyle = "#ffffff";
      ctx.fill();
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, []);

  return <canvas ref={canvasRef} className="pitch-canvas" aria-label="Tactical pitch view" />;
}
