import * as THREE from "three";
import { addBoards, addCornerFlags, ballTexture } from "./figures";
import { L, W, drawGrass, drawMarkings } from "./shared";

/** The broadcast stadium, shared by the live 3D view and the offline video renderer (auto-eventing). */

export const SCALE_UP = 1.35; // players drawn slightly larger than life so the broadcast camera reads them

export const toWorld = (x: number, y: number, z = 0) => new THREE.Vector3(x - L / 2, z, -(y - W / 2));

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

export function makeRenderer(preserveDrawingBuffer = false): THREE.WebGLRenderer {
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance", preserveDrawingBuffer });
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  return renderer;
}

export interface Stadium {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  ball: THREE.Mesh;
  ballShadow: THREE.Mesh;
  boardTextures: THREE.CanvasTexture[];
}

/** Lights, pitch, boards, stands, goals and the ball. */
export function buildStadium(): Stadium {
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
  const standMat = new THREE.MeshStandardMaterial({ map: crowdTexture(), roughness: 1 });
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
  const ballShadow = new THREE.Mesh(
    new THREE.CircleGeometry(0.45, 16),
    new THREE.MeshBasicMaterial({ color: "#000", transparent: true, opacity: 0.35 }),
  );
  ballShadow.rotation.x = -Math.PI / 2;
  scene.add(ballShadow);
  return { scene, camera, ball, ballShadow, boardTextures };
}

/** Roll the ball mesh to a new world position. */
export function placeBall(s: Stadium, last: THREE.Vector3, bw: THREE.Vector3): void {
  const roll = bw.clone().sub(last);
  roll.y = 0;
  if (roll.lengthSq() > 1e-6 && roll.lengthSq() < 25) {
    const axis = new THREE.Vector3(roll.z, 0, -roll.x).normalize();
    s.ball.rotateOnWorldAxis(axis, roll.length() / 0.3);
  }
  last.copy(bw);
  s.ball.position.copy(bw);
  s.ballShadow.position.set(bw.x, 0.03, bw.z);
}

/** The TV camera: high on the near touchline, panning with the ball (eased by `k` per frame). */
export function tvCamera(target: THREE.Vector3, camPos: THREE.Vector3, ballWorld: THREE.Vector3, k = 1): void {
  target.lerp(new THREE.Vector3(ballWorld.x * 0.95, 0, ballWorld.z * 0.6), 0.06 * k);
  camPos.lerp(new THREE.Vector3(Math.max(-36, Math.min(36, ballWorld.x * 0.82)), 21, W / 2 + 33), 0.05 * k);
}
