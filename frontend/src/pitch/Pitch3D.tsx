import { useEffect, useRef } from "react";
import * as THREE from "three";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { useStore } from "../store";
import { animateRig, buildPlayer, type Rig } from "./figures";
import { contrastText, sample } from "./shared";
import { SCALE_UP, buildStadium, makeRenderer, placeBall, toWorld, tvCamera } from "./stadium";

/** Per-frame easing tuned at 60 fps, made frame-rate independent (slow GPUs still catch up in about a second). */
const ease = (at60: number, dt: number) => 1 - Math.pow(1 - at60, dt * 60);

interface Figure {
  rig: Rig;
  group: THREE.Group;
  ring: THREE.Mesh;
  label: CSS2DObject;
  labelEl: HTMLDivElement;
  last: THREE.Vector3;
}

export function Pitch3D() {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = hostRef.current!;
    const renderer = makeRenderer();
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
    host.appendChild(renderer.domElement);
    const labels = new CSS2DRenderer();
    labels.domElement.className = "pitch3d-labels";
    host.appendChild(labels.domElement);

    const stadium = buildStadium();
    const { scene, camera, boardTextures } = stadium;
    const lastBall = new THREE.Vector3();

    const figures = new Map<string, Figure>();
    const skin = ["#f1c27d", "#c68642", "#8d5524", "#e0ac69", "#ffdbac", "#a0662f"];
    const hair = ["#1f1308", "#3b2414", "#0b0b0b", "#6b4423", "#d6b370"];
    const ringGeo = new THREE.RingGeometry(0.62, 0.82, 28);

    function figureFor(id: string): Figure {
      let f = figures.get(id);
      if (f) return f;
      const { players, clubs } = useStore.getState();
      const pl = players[id];
      const club = pl ? clubs[pl.club_id] : undefined;
      const gk = pl?.group === "GK";
      const shirt = gk ? "#facc15" : club?.primary ?? "#999";
      const seed = (pl?.number ?? 0) + (pl?.name.length ?? 0);
      const rig = buildPlayer({
        shirt,
        shorts: gk ? "#111827" : club?.secondary ?? "#222",
        socks: gk ? "#facc15" : club?.primary ?? "#999",
        skin: skin[seed % skin.length],
        hair: hair[(seed * 7) % hair.length],
        number: pl?.number ?? 0,
        name: pl?.short_name ?? "",
        printColor: contrastText(shirt),
        gk,
      });
      const group = rig.root;
      const ring = new THREE.Mesh(
        ringGeo,
        new THREE.MeshBasicMaterial({ color: "#fbbf24", transparent: true, opacity: 0.9, side: THREE.DoubleSide }),
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = 0.04;
      ring.visible = false;
      group.add(ring);
      group.scale.setScalar(SCALE_UP);
      const labelEl = document.createElement("div");
      labelEl.className = "tag3d";
      const label = new CSS2DObject(labelEl);
      label.position.set(0, 2.35, 0);
      label.visible = false;
      group.add(label);
      scene.add(group);
      f = { rig, group, ring, label, labelEl, last: new THREE.Vector3() };
      figures.set(id, f);
      return f;
    }

    // Player Cam target: your chosen player or captain if they are in this match, else one of your squad who is,
    // else the player on the ball (kept for a few seconds so the camera does not jump with every touch)
    let followId: string | null = null;
    let followSince = 0;
    const pickFollow = (s: NonNullable<ReturnType<typeof sample>>, now: number): string | null => {
      const st = useStore.getState();
      const preferred = st.fan?.focus_player ?? st.fan?.captain ?? null;
      if (preferred && s.players.has(preferred)) return preferred;
      const squad = st.fan?.squad ?? [];
      const mine = squad.find((id) => s.players.has(id));
      if (mine) return mine;
      if (followId && s.players.has(followId) && now - followSince < 4000) return followId;
      if (s.owner && s.players.has(s.owner)) return s.owner;
      let best: string | null = null;
      let dmin = Infinity;
      for (const [id, p] of s.players) {
        const d = Math.hypot(p.x - s.ball[0], p.y - s.ball[1]);
        if (d < dmin) [best, dmin] = [id, d];
      }
      return best;
    };

    const target = new THREE.Vector3();
    const camPos = new THREE.Vector3(0, 30, 80);
    let raf = 0;
    let stageSeen: string | null = null;

    const resize = () => {
      const w = host.clientWidth;
      const h = host.clientHeight;
      renderer.setSize(w, h);
      labels.setSize(w, h);
      camera.aspect = w / Math.max(1, h);
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(host);
    resize();

    let lastNow = performance.now();
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const dt = Math.min(0.1, (now - lastNow) / 1000);
      lastNow = now;
      for (const t of boardTextures) t.offset.x = (t.offset.x + dt * 0.02) % 1;
      const st = useStore.getState();
      if (st.stage !== stageSeen) {
        for (const f of figures.values()) {
          scene.remove(f.group);
          f.labelEl.remove(); // CSS2D elements of removed children are not cleaned up by three.js
        }
        figures.clear();
        stageSeen = st.stage;
        followId = null;
      }
      const s = sample(now);
      if (s) {
        const squad = new Set(st.fan?.squad ?? []);
        const anchors = new Map<string, string>();
        for (const o of st.overlays) {
          const pid = o.moment.overlay.anchor?.player_id;
          if (!pid || o.until < now) continue;
          const f = o.moment.facts;
          anchors.set(pid, o.template === "player_tag" && f.speed_kmh ? `${f.speed_kmh.toFixed(1)} km/h` : "");
        }
        const seen = new Set<string>();
        for (const [id, p] of s.players) {
          seen.add(id);
          const f = figureFor(id);
          const pos = toWorld(p.x, p.y);
          f.group.position.copy(pos);
          const d = pos.clone().sub(f.last);
          if (d.lengthSq() > 0.0004) {
            const want = Math.atan2(d.x, d.z);
            const diff = Math.atan2(Math.sin(want - f.group.rotation.y), Math.cos(want - f.group.rotation.y));
            f.group.rotation.y += diff * Math.min(1, dt * 10); // turn smoothly instead of snapping
          }
          f.last.copy(pos);
          animateRig(f.rig, p.kmh / 3.6, dt);
          const inSquad = squad.has(id);
          f.ring.visible = inSquad;
          (f.ring.material as THREE.MeshBasicMaterial).color.set(id === st.fan?.captain ? "#fde047" : "#f59e0b");
          const pl = st.players[id];
          const show = inSquad || id === s.owner || anchors.has(id) || id === st.fan?.focus_player || id === followId;
          f.label.visible = show;
          if (show) {
            const extra = anchors.get(id);
            const cap = id === st.fan?.captain ? " ©" : "";
            const html = `${pl?.short_name ?? id}${cap}${extra ? `<b>${extra}</b>` : ""}`;
            if (f.labelEl.innerHTML !== html) f.labelEl.innerHTML = html;
            f.labelEl.className = `tag3d${inSquad ? " squad" : ""}${extra ? " hot" : ""}`;
          }
        }
        for (const [id, f] of figures) {
          if (!seen.has(id)) f.group.visible = false;
          else f.group.visible = true;
        }
        const bw = toWorld(s.ball[0], s.ball[1], 0.3 + s.ball[2]);
        placeBall(stadium, lastBall, bw);

        // Camera direction
        let focus = new THREE.Vector3(bw.x, 0, bw.z);
        const camMode = st.camera;
        if (camMode === "player") {
          const pick = pickFollow(s, now);
          if (pick !== followId) [followId, followSince] = [pick, now];
        } else {
          followId = null;
        }
        if (st.following !== followId) useStore.setState({ following: followId });
        const follow = followId ? s.players.get(followId) : undefined;
        if (camMode === "tactical") {
          target.lerp(new THREE.Vector3(0, 0, 0), ease(0.05, dt));
          camPos.lerp(new THREE.Vector3(0, 92, 22), ease(0.05, dt));
        } else if (follow) {
          const fp = toWorld(follow.x, follow.y);
          const m = st.matches[st.stage ?? ""];
          const pl = st.players[followId!];
          const homeSide = m && pl ? pl.club_id === m.home : true;
          const attackRight = (m?.period ?? 1) === 1 ? homeSide : !homeSide;
          const dir = attackRight ? 1 : -1;
          focus = fp.clone().add(new THREE.Vector3(dir * 10, 0, 0));
          target.lerp(focus, ease(0.08, dt));
          camPos.lerp(fp.clone().add(new THREE.Vector3(-dir * 15, 7.5, 7)), ease(0.06, dt));
        } else {
          tvCamera(target, camPos, focus, dt * 60);
        }
        camera.position.copy(camPos);
        camera.lookAt(target);
      }
      renderer.render(scene, camera);
      labels.render(scene, camera);
    };
    raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      renderer.dispose();
      host.removeChild(renderer.domElement);
      host.removeChild(labels.domElement);
    };
  }, []);

  return <div ref={hostRef} className="pitch3d" aria-label="3D broadcast view" />;
}
