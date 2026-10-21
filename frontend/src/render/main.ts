import * as THREE from "three";
import { animateRig, buildPlayer, type Rig } from "../pitch/figures";
import { L, W, contrastText } from "../pitch/shared";
import { SCALE_UP, buildStadium, makeRenderer, placeBall, toWorld, tvCamera } from "../pitch/stadium";

/**
 * Offline broadcast renderer for auto-eventing (footballytics.vision).
 *
 * Playwright drives it one frame at a time: the same stadium, players and TV camera as the live 3D view, rendered
 * deterministically from simulator tracking. Each frame returns the image plus what a calibrated broadcast camera
 * would know (pitch-to-pixel correspondences) and the ground truth the vision pipeline is scored against
 * (each player's on-screen box, the ball's pixel position).
 */

interface PlayerMeta {
  id: string;
  number: number;
  name: string;
  shirt: string;
  shorts: string;
  socks: string;
  gk: boolean;
}

interface Setup {
  width: number;
  height: number;
  players: PlayerMeta[];
}

/** One video frame: players [id, x, y, km/h] and ball [x, y, z] in pitch metres; dt in seconds. */
interface Frame {
  p: [string, number, number, number][];
  b: [number, number, number];
  dt: number;
}

interface FrameOut {
  image: string; // data URL (JPEG)
  ground: [number, number, number, number][]; // pitch x, y -> pixel u, v
  boxes: Record<string, [number, number, number, number]>; // player id -> x1, y1, x2, y2 (pixels, clipped)
  ball: [number, number] | null;
}

declare global {
  interface Window {
    fbx: { setup(s: Setup): void; frame(f: Frame): FrameOut };
  }
}

const SKIN = ["#f1c27d", "#c68642", "#8d5524", "#e0ac69", "#ffdbac", "#a0662f"];
const HAIR = ["#1f1308", "#3b2414", "#0b0b0b", "#6b4423", "#d6b370"];

let renderer: THREE.WebGLRenderer;
let stadium: ReturnType<typeof buildStadium>;
let size = { w: 1280, h: 720 };
const rigs = new Map<string, { rig: Rig; group: THREE.Group; last: THREE.Vector3 }>();
const target = new THREE.Vector3();
const camPos = new THREE.Vector3(0, 30, 80);
const lastBall = new THREE.Vector3();
let started = false;

function setup(s: Setup): void {
  size = { w: s.width, h: s.height };
  renderer = makeRenderer(true);
  renderer.setPixelRatio(1);
  renderer.setSize(s.width, s.height);
  document.body.appendChild(renderer.domElement);
  stadium = buildStadium();
  stadium.camera.aspect = s.width / s.height;
  stadium.camera.updateProjectionMatrix();
  for (const p of s.players) {
    let seed = 0;
    for (const ch of p.id) seed = (seed * 31 + ch.charCodeAt(0)) >>> 0;
    const rig = buildPlayer({
      shirt: p.shirt,
      shorts: p.shorts,
      socks: p.socks,
      skin: SKIN[seed % SKIN.length],
      hair: HAIR[(seed >>> 3) % HAIR.length],
      number: p.number,
      name: p.name,
      printColor: contrastText(p.shirt),
      gk: p.gk,
    });
    rig.root.scale.setScalar(SCALE_UP);
    rig.root.visible = false;
    stadium.scene.add(rig.root);
    rigs.set(p.id, { rig, group: rig.root, last: new THREE.Vector3() });
  }
}

const project = (v: THREE.Vector3): [number, number, boolean] => {
  const p = v.clone().project(stadium.camera);
  return [((p.x + 1) / 2) * size.w, ((1 - p.y) / 2) * size.h, p.z < 1 && p.z > -1];
};

function frame(f: Frame): FrameOut {
  const seen = new Set<string>();
  for (const [id, x, y, kmh] of f.p) {
    const r = rigs.get(id);
    if (!r) continue;
    seen.add(id);
    const pos = toWorld(x, y);
    const d = pos.clone().sub(r.last);
    if (started && d.lengthSq() > 0.0004) {
      const want = Math.atan2(d.x, d.z);
      const diff = Math.atan2(Math.sin(want - r.group.rotation.y), Math.cos(want - r.group.rotation.y));
      r.group.rotation.y += diff * Math.min(1, f.dt * 10);
    }
    r.last.copy(pos);
    r.group.position.copy(pos);
    animateRig(r.rig, kmh / 3.6, f.dt);
  }
  for (const [id, r] of rigs) r.group.visible = seen.has(id);
  for (const t of stadium.boardTextures) t.offset.x = (t.offset.x + f.dt * 0.02) % 1;

  const bw = toWorld(f.b[0], f.b[1], 0.3 + f.b[2]);
  placeBall(stadium, lastBall, bw);
  const focus = new THREE.Vector3(bw.x, 0, bw.z);
  if (!started) {
    for (let i = 0; i < 300; i++) tvCamera(target, camPos, focus); // settle on the first frame
    started = true;
  } else {
    tvCamera(target, camPos, focus, f.dt * 60); // same easing per second as the live view at 60 fps
  }
  const cam = stadium.camera;
  cam.position.copy(camPos);
  cam.lookAt(target);
  cam.updateMatrixWorld();
  renderer.render(stadium.scene, cam);

  const ground: FrameOut["ground"] = [];
  for (let gx = 0; gx <= 4; gx++) {
    for (let gy = 0; gy <= 4; gy++) {
      const x = (gx * L) / 4;
      const y = (gy * W) / 4;
      const [u, v, ok] = project(toWorld(x, y));
      if (ok) ground.push([x, y, u, v]);
    }
  }
  const boxes: FrameOut["boxes"] = {};
  const box = new THREE.Box3();
  const corner = new THREE.Vector3();
  for (const id of seen) {
    box.setFromObject(rigs.get(id)!.group);
    let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
    let front = true;
    for (let i = 0; i < 8; i++) {
      corner.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z);
      const [u, v, ok] = project(corner);
      front &&= ok;
      x1 = Math.min(x1, u); y1 = Math.min(y1, v); x2 = Math.max(x2, u); y2 = Math.max(y2, v);
    }
    const cx1 = Math.max(0, x1), cy1 = Math.max(0, y1), cx2 = Math.min(size.w, x2), cy2 = Math.min(size.h, y2);
    if (front && cx2 - cx1 > 2 && cy2 - cy1 > 2) boxes[id] = [cx1, cy1, cx2, cy2].map((n) => Math.round(n * 10) / 10) as [number, number, number, number];
  }
  const [bu, bv, bok] = project(bw);
  const ball: FrameOut["ball"] = bok && bu >= 0 && bu < size.w && bv >= 0 && bv < size.h ? [bu, bv] : null;
  return { image: renderer.domElement.toDataURL("image/jpeg", 0.92), ground, boxes, ball };
}

window.fbx = { setup, frame };
