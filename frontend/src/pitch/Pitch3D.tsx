import { useEffect, useRef } from "react";
import * as THREE from "three";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { useStore } from "../store";
import { addBoards, addCornerFlags, animateRig, ballTexture, buildPlayer, type Rig } from "./figures";
import { L, W, contrastText, drawGrass, drawMarkings, sample } from "./shared";

const SCALE_UP = 1.35; // players drawn slightly larger than life so the broadcast camera reads them

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
  ctx.fillStyle = "#1a2440";
  ctx.fillRect(0, 0, c.width, c.height);
  const palette = ["#3b82f6", "#ef4444", "#f1f5f9", "#facc15", "#14b8a6", "#64748b", "#a78bfa", "#fb923c"];
  for (let i = 0; i < 22000; i++) {
    ctx.fillStyle = palette[Math.floor(Math.random() * palette.length)];
    ctx.globalAlpha = 0.55 + Math.random() * 0.45;
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
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    host.appendChild(renderer.domElement);
    const labels = new CSS2DRenderer();
    labels.domElement.className = "pitch3d-labels";
    host.appendChild(labels.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#070b16");
    scene.fog = new THREE.Fog("#070b16", 140, 260);
    const camera = new THREE.PerspectiveCamera(30, 16 / 9, 0.5, 600);
    camera.position.set(0, 30, 80);

    scene.add(new THREE.HemisphereLight("#dbeafe", "#1e293b", 0.95));
    const sun = new THREE.DirectionalLight("#fff8ec", 2.1); // floodlight key light with soft shadows
    sun.position.set(-35, 70, 45);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -62, right: 62, top: 44, bottom: -44, near: 10, far: 200 });
    sun.shadow.bias = -0.0004;
    scene.add(sun);
    const fill = new THREE.DirectionalLight("#bfdbfe", 0.45);
    fill.position.set(40, 40, -50);
    scene.add(fill);

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
    pitch.receiveShadow = true;
    scene.add(pitch);
    const boardTextures = addBoards(scene, L, W);
    addCornerFlags(scene, L, W);
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
      new THREE.SphereGeometry(0.3, 24, 18),
      new THREE.MeshStandardMaterial({ map: ballTexture(), emissive: "#333", roughness: 0.35 }),
    );
    ball.castShadow = true;
    scene.add(ball);
    const lastBall = new THREE.Vector3();
    const ballShadow = new THREE.Mesh(
      new THREE.CircleGeometry(0.45, 16),
      new THREE.MeshBasicMaterial({ color: "#000", transparent: true, opacity: 0.35 }),
    );
    ballShadow.rotation.x = -Math.PI / 2;
    scene.add(ballShadow);

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
        const bw = toWorld(s.ball[0], s.ball[1], 0.3 + s.ball[2]);
        const roll = bw.clone().sub(lastBall);
        roll.y = 0;
        if (roll.lengthSq() > 1e-6 && roll.lengthSq() < 25) {
          const axis = new THREE.Vector3(roll.z, 0, -roll.x).normalize();
          ball.rotateOnWorldAxis(axis, roll.length() / 0.3);
        }
        lastBall.copy(bw);
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
