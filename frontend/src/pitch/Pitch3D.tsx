import { useEffect, useRef } from "react";
import * as THREE from "three";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { useStore } from "../store";
import { L, W, drawGrass, drawMarkings, sample } from "./shared";

const SCALE_UP = 1.45; // players drawn slightly larger than life so the broadcast camera reads them

const toWorld = (x: number, y: number, z = 0) => new THREE.Vector3(x - L / 2, z, -(y - W / 2));

function pitchTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  const px = 18;
  const margin = 6;
  c.width = (L + margin * 2) * px;
  c.height = (W + margin * 2) * px;
  const ctx = c.getContext("2d")!;
  ctx.fillStyle = "#1b6b35";
  ctx.fillRect(0, 0, c.width, c.height);
  ctx.setTransform(px, 0, 0, px, margin * px, margin * px);
  drawGrass(ctx, "#23843f", "#1d7537");
  // subtle mowing noise
  for (let i = 0; i < 9000; i++) {
    ctx.fillStyle = `rgba(0,0,0,${Math.random() * 0.05})`;
    ctx.fillRect(Math.random() * L, Math.random() * W, 0.15, 0.15);
  }
  drawMarkings(ctx, 0.14, "rgba(255,255,255,0.92)");
  const tex = new THREE.CanvasTexture(c);
  tex.anisotropy = 8;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function crowdTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 1024;
  c.height = 256;
  const ctx = c.getContext("2d")!;
  ctx.fillStyle = "#0d1426";
  ctx.fillRect(0, 0, c.width, c.height);
  const palette = ["#1e3a8a", "#b91c1c", "#e5e7eb", "#facc15", "#0f766e", "#334155", "#7c3aed"];
  for (let i = 0; i < 14000; i++) {
    ctx.fillStyle = palette[Math.floor(Math.random() * palette.length)];
    ctx.globalAlpha = 0.35 + Math.random() * 0.5;
    ctx.fillRect(Math.random() * c.width, Math.random() * c.height, 2, 3);
  }
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = THREE.RepeatWrapping;
  tex.repeat.set(4, 1);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makeGoal(x: number): THREE.Group {
  const g = new THREE.Group();
  const white = new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.4 });
  const post = new THREE.CylinderGeometry(0.07, 0.07, 2.44, 10);
  for (const y of [W / 2 - 3.66, W / 2 + 3.66]) {
    const m = new THREE.Mesh(post, white);
    m.position.copy(toWorld(x, y, 1.22));
    g.add(m);
  }
  const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 7.32, 10), white);
  bar.rotation.x = Math.PI / 2;
  bar.position.copy(toWorld(x, W / 2, 2.44));
  g.add(bar);
  const depth = 2.0 * (x === 0 ? -1 : 1);
  const net = new THREE.Mesh(
    new THREE.BoxGeometry(Math.abs(depth), 2.44, 7.32),
    new THREE.MeshBasicMaterial({ color: "#ffffff", wireframe: true, transparent: true, opacity: 0.18 }),
  );
  net.position.copy(toWorld(x + depth / 2, W / 2, 1.22));
  g.add(net);
  return g;
}

interface Figure {
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
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);
    const labels = new CSS2DRenderer();
    labels.domElement.className = "pitch3d-labels";
    host.appendChild(labels.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#070b16");
    scene.fog = new THREE.Fog("#070b16", 140, 260);
    const camera = new THREE.PerspectiveCamera(30, 16 / 9, 0.5, 600);
    camera.position.set(0, 30, 80);

    scene.add(new THREE.HemisphereLight("#dbeafe", "#1e293b", 0.9));
    const sun = new THREE.DirectionalLight("#ffffff", 1.6);
    sun.position.set(-40, 80, 50);
    scene.add(sun);

    // Ground, pitch, stands
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(240, 180), new THREE.MeshStandardMaterial({ color: "#14532d" }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.02;
    scene.add(ground);
    const pitch = new THREE.Mesh(
      new THREE.PlaneGeometry(L + 12, W + 12),
      new THREE.MeshStandardMaterial({ map: pitchTexture(), roughness: 0.95 }),
    );
    pitch.rotation.x = -Math.PI / 2;
    scene.add(pitch);
    const crowd = crowdTexture();
    const standMat = new THREE.MeshStandardMaterial({ map: crowd, roughness: 1 });
    // Four tilted stands facing the pitch (x, z, width)
    const stands: [number, number, number][] = [
      [0, -W / 2 - 22, L + 40],
      [0, W / 2 + 22, L + 40],
      [-L / 2 - 22, 0, W + 20],
      [L / 2 + 22, 0, W + 20],
    ];
    for (const [x, z, w] of stands) {
      const s = new THREE.Mesh(new THREE.PlaneGeometry(w, 26), standMat);
      s.position.set(x, 9, z);
      s.lookAt(0, -18, 0); // a plane's front (+Z) faces the pitch
      scene.add(s);
    }
    scene.add(makeGoal(0), makeGoal(L));

    const ball = new THREE.Mesh(
      new THREE.SphereGeometry(0.34, 20, 16),
      new THREE.MeshStandardMaterial({ color: "#ffffff", emissive: "#555", roughness: 0.3 }),
    );
    scene.add(ball);
    const ballShadow = new THREE.Mesh(
      new THREE.CircleGeometry(0.45, 16),
      new THREE.MeshBasicMaterial({ color: "#000", transparent: true, opacity: 0.35 }),
    );
    ballShadow.rotation.x = -Math.PI / 2;
    scene.add(ballShadow);

    const figures = new Map<string, Figure>();
    const skin = ["#f1c27d", "#c68642", "#8d5524", "#e0ac69", "#ffdbac"];
    const geo = {
      legs: new THREE.CylinderGeometry(0.2, 0.17, 0.85, 10),
      torso: new THREE.CylinderGeometry(0.3, 0.26, 0.75, 12),
      head: new THREE.SphereGeometry(0.17, 12, 10),
      shadow: new THREE.CircleGeometry(0.5, 16),
      ring: new THREE.RingGeometry(0.62, 0.82, 28),
    };
    const shadowMat = new THREE.MeshBasicMaterial({ color: "#000", transparent: true, opacity: 0.3 });

    function figureFor(id: string): Figure {
      let f = figures.get(id);
      if (f) return f;
      const { players, clubs } = useStore.getState();
      const pl = players[id];
      const club = pl ? clubs[pl.club_id] : undefined;
      const kit = pl?.group === "GK" ? "#facc15" : club?.primary ?? "#999";
      const group = new THREE.Group();
      const legs = new THREE.Mesh(geo.legs, new THREE.MeshStandardMaterial({ color: club?.secondary ?? "#222" }));
      legs.position.y = 0.43;
      const torso = new THREE.Mesh(geo.torso, new THREE.MeshStandardMaterial({ color: kit, roughness: 0.6 }));
      torso.position.y = 1.22;
      const head = new THREE.Mesh(
        geo.head,
        new THREE.MeshStandardMaterial({ color: skin[(pl?.number ?? 0) % skin.length] }),
      );
      head.position.y = 1.78;
      const shadow = new THREE.Mesh(geo.shadow, shadowMat);
      shadow.rotation.x = -Math.PI / 2;
      shadow.position.y = 0.02;
      const ring = new THREE.Mesh(
        geo.ring,
        new THREE.MeshBasicMaterial({ color: "#fbbf24", transparent: true, opacity: 0.9, side: THREE.DoubleSide }),
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = 0.04;
      ring.visible = false;
      group.add(legs, torso, head, shadow, ring);
      group.scale.setScalar(SCALE_UP);
      const labelEl = document.createElement("div");
      labelEl.className = "tag3d";
      const label = new CSS2DObject(labelEl);
      label.position.set(0, 2.5, 0);
      label.visible = false;
      group.add(label);
      scene.add(group);
      f = { group, ring, label, labelEl, last: new THREE.Vector3() };
      figures.set(id, f);
      return f;
    }

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

    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const st = useStore.getState();
      if (st.stage !== stageSeen) {
        for (const f of figures.values()) {
          scene.remove(f.group);
          f.labelEl.remove(); // CSS2D elements of removed children are not cleaned up by three.js
        }
        figures.clear();
        stageSeen = st.stage;
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
          if (d.lengthSq() > 0.0004) f.group.rotation.y = Math.atan2(d.x, d.z);
          f.last.copy(pos);
          const inSquad = squad.has(id);
          f.ring.visible = inSquad;
          (f.ring.material as THREE.MeshBasicMaterial).color.set(id === st.fan?.captain ? "#fde047" : "#f59e0b");
          const pl = st.players[id];
          const show = inSquad || id === s.owner || anchors.has(id) || id === st.fan?.focus_player;
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
        const bw = toWorld(s.ball[0], s.ball[1], 0.34 + s.ball[2]);
        ball.position.copy(bw);
        ballShadow.position.set(bw.x, 0.03, bw.z);

        // Camera direction
        let focus = new THREE.Vector3(bw.x, 0, bw.z);
        const camMode = st.camera;
        const followId = st.fan?.focus_player ?? st.fan?.captain;
        const follow = camMode === "player" && followId ? s.players.get(followId) : undefined;
        if (camMode === "tactical") {
          target.lerp(new THREE.Vector3(0, 0, 0), 0.05);
          camPos.lerp(new THREE.Vector3(0, 92, 22), 0.05);
        } else if (follow) {
          const fp = toWorld(follow.x, follow.y);
          const m = st.matches[st.stage ?? ""];
          const pl = st.players[followId!];
          const homeSide = m && pl ? pl.club_id === m.home : true;
          const attackRight = (m?.period ?? 1) === 1 ? homeSide : !homeSide;
          const dir = attackRight ? 1 : -1;
          focus = fp.clone().add(new THREE.Vector3(dir * 10, 0, 0));
          target.lerp(focus, 0.08);
          camPos.lerp(fp.clone().add(new THREE.Vector3(-dir * 15, 7.5, 7)), 0.06);
        } else {
          target.lerp(new THREE.Vector3(focus.x * 0.95, 0, focus.z * 0.6), 0.06);
          camPos.lerp(new THREE.Vector3(Math.max(-36, Math.min(36, focus.x * 0.82)), 21, W / 2 + 33), 0.05);
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
