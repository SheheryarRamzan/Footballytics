import * as THREE from "three";

/** Articulated low-poly footballer: kit colours, shirt number and name on the back, speed-driven running cycle. */
export interface Rig {
  root: THREE.Group;
  body: THREE.Group;
  legL: THREE.Group;
  legR: THREE.Group;
  armL: THREE.Group;
  armR: THREE.Group;
  phase: number;
}

const G = {
  torso: new THREE.CapsuleGeometry(0.17, 0.34, 4, 12),
  shorts: new THREE.CylinderGeometry(0.19, 0.21, 0.24, 12),
  neck: new THREE.CylinderGeometry(0.055, 0.06, 0.1, 8),
  head: new THREE.SphereGeometry(0.115, 16, 12),
  hair: new THREE.SphereGeometry(0.122, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2.1),
  sleeve: new THREE.CapsuleGeometry(0.058, 0.12, 3, 8),
  forearm: new THREE.CapsuleGeometry(0.045, 0.2, 3, 8),
  glove: new THREE.SphereGeometry(0.06, 8, 6),
  thigh: new THREE.CapsuleGeometry(0.068, 0.24, 3, 8),
  shin: new THREE.CapsuleGeometry(0.056, 0.3, 3, 8),
  boot: new THREE.BoxGeometry(0.09, 0.07, 0.22),
  back: new THREE.PlaneGeometry(0.26, 0.3),
};

const materials = new Map<string, THREE.MeshStandardMaterial>();
function mat(color: string, roughness = 0.75): THREE.MeshStandardMaterial {
  const key = `${color}|${roughness}`;
  let m = materials.get(key);
  if (!m) {
    m = new THREE.MeshStandardMaterial({ color, roughness });
    materials.set(key, m);
  }
  return m;
}

function backPrint(number: number, name: string, color: string): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 128;
  c.height = 148;
  const ctx = c.getContext("2d")!;
  ctx.fillStyle = color;
  ctx.textAlign = "center";
  ctx.font = "bold 22px system-ui, sans-serif";
  ctx.fillText(name.toUpperCase().slice(0, 11), 64, 26);
  ctx.font = "bold 96px system-ui, sans-serif";
  ctx.fillText(String(number), 64, 128);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

function mesh(geo: THREE.BufferGeometry, material: THREE.Material, y = 0, x = 0, z = 0): THREE.Mesh {
  const m = new THREE.Mesh(geo, material);
  m.position.set(x, y, z);
  m.castShadow = true;
  return m;
}

export function buildPlayer(o: {
  shirt: string;
  shorts: string;
  socks: string;
  skin: string;
  hair: string;
  number: number;
  name: string;
  printColor: string;
  gk: boolean;
}): Rig {
  const root = new THREE.Group();
  const body = new THREE.Group();
  body.position.y = 0.95; // hips
  root.add(body);

  body.add(mesh(G.shorts, mat(o.shorts), 0.02));
  body.add(mesh(G.torso, mat(o.shirt, 0.65), 0.42));
  body.add(mesh(G.neck, mat(o.skin), 0.74));
  body.add(mesh(G.head, mat(o.skin, 0.6), 0.86));
  body.add(mesh(G.hair, mat(o.hair, 0.9), 0.875));
  const print = new THREE.Mesh(
    G.back,
    new THREE.MeshBasicMaterial({ map: backPrint(o.number, o.name, o.printColor), transparent: true }),
  );
  print.position.set(0, 0.45, -0.178);
  print.rotation.y = Math.PI;
  body.add(print);

  const arm = (side: number) => {
    const g = new THREE.Group();
    g.position.set(side * 0.235, 0.66, 0);
    g.add(mesh(G.sleeve, mat(o.shirt, 0.65), -0.08));
    g.add(mesh(G.forearm, mat(o.skin), -0.3));
    if (o.gk) g.add(mesh(G.glove, mat("#f8fafc", 0.5), -0.45));
    body.add(g);
    return g;
  };
  const leg = (side: number) => {
    const g = new THREE.Group();
    g.position.set(side * 0.1, 0.95, 0);
    g.add(mesh(G.thigh, mat(o.skin), -0.22));
    g.add(mesh(G.shin, mat(o.socks), -0.62));
    g.add(mesh(G.boot, mat("#111827", 0.4), -0.9, 0, 0.04));
    root.add(g);
    return g;
  };
  return { root, body, armL: arm(-1), armR: arm(1), legL: leg(-1), legR: leg(1), phase: Math.random() * 6 };
}

/** Running cycle: stride frequency and swing grow with speed; slight forward lean when sprinting. */
export function animateRig(r: Rig, speedMps: number, dt: number): void {
  const amp = Math.min(1, speedMps / 7.5);
  r.phase += dt * (2.2 + speedMps * 1.25);
  const s = Math.sin(r.phase);
  r.legL.rotation.x = s * 0.85 * amp;
  r.legR.rotation.x = -s * 0.85 * amp;
  r.armL.rotation.x = -s * 0.7 * amp;
  r.armR.rotation.x = s * 0.7 * amp;
  r.body.rotation.x = 0.14 * amp;
  r.body.position.y = 0.95 + Math.abs(Math.cos(r.phase)) * 0.045 * amp;
}

/** Classic panelled match ball (equirectangular texture). */
export function ballTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 256;
  const ctx = c.getContext("2d")!;
  ctx.fillStyle = "#f8fafc";
  ctx.fillRect(0, 0, 512, 256);
  ctx.fillStyle = "#111827";
  const spots: [number, number, number][] = [
    [64, 128, 30], [192, 128, 30], [320, 128, 30], [448, 128, 30],
    [0, 40, 26], [128, 40, 26], [256, 40, 26], [384, 40, 26], [512, 40, 26],
    [0, 216, 26], [128, 216, 26], [256, 216, 26], [384, 216, 26], [512, 216, 26],
  ];
  for (const [x, y, r] of spots) {
    ctx.beginPath();
    for (let i = 0; i < 5; i++) {
      const a = (i / 5) * Math.PI * 2 - Math.PI / 2;
      ctx.lineTo(x + Math.cos(a) * r, y + Math.sin(a) * r * 0.8);
    }
    ctx.fill();
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** LED perimeter boards with a scrolling message; returns textures to animate. */
export function addBoards(scene: THREE.Scene, L: number, W: number): THREE.CanvasTexture[] {
  const textures: THREE.CanvasTexture[] = [];
  const msg = "FOOTBALLYTICS  ◆  YOUR MATCHDAY  ◆  EVERY MATCH, MADE FOR YOU  ◆  ";
  const font = "bold 40px system-ui, sans-serif";
  const probe = document.createElement("canvas").getContext("2d")!;
  probe.font = font;
  const msgW = Math.ceil(probe.measureText(msg).width);
  const make = (len: number) => {
    const c = document.createElement("canvas");
    c.width = msgW * 2; // exact multiple of the message: the texture tiles seamlessly
    c.height = 64;
    const ctx = c.getContext("2d")!;
    ctx.fillStyle = "#0e5e57";
    ctx.fillRect(0, 0, c.width, 64);
    ctx.font = font;
    ctx.fillStyle = "#e0fff6";
    ctx.textBaseline = "middle";
    ctx.fillText(msg, 0, 34);
    ctx.fillText(msg, msgW, 34);
    const t = new THREE.CanvasTexture(c);
    t.wrapS = THREE.RepeatWrapping;
    t.repeat.set(len / (msgW / 20), 1);
    t.colorSpace = THREE.SRGBColorSpace;
    textures.push(t);
    return new THREE.MeshBasicMaterial({ map: t });
  };
  const placements: [number, number, number, number][] = [
    // x, z, length, rotationY
    [0, W / 2 + 4.5, L + 6, Math.PI],
    [0, -(W / 2 + 4.5), L + 6, 0],
    [-(L / 2 + 4.5), 0, W - 14, Math.PI / 2],
    [L / 2 + 4.5, 0, W - 14, -Math.PI / 2],
  ];
  for (const [x, z, len, ry] of placements) {
    const board = new THREE.Mesh(new THREE.PlaneGeometry(len, 0.9), make(len));
    board.position.set(x, 0.45, z);
    board.rotation.y = ry;
    scene.add(board);
    const backing = new THREE.Mesh(new THREE.BoxGeometry(len, 0.92, 0.2), mat("#0f172a"));
    backing.position.set(x, 0.45, z);
    backing.rotation.y = ry;
    backing.translateZ(-0.12);
    scene.add(backing);
  }
  return textures;
}

export function addCornerFlags(scene: THREE.Scene, L: number, W: number): void {
  const pole = new THREE.CylinderGeometry(0.025, 0.025, 1.5, 6);
  const flag = new THREE.PlaneGeometry(0.4, 0.28);
  for (const sx of [-1, 1])
    for (const sz of [-1, 1]) {
      const p = new THREE.Mesh(pole, mat("#f8fafc"));
      p.position.set(sx * (L / 2), 0.75, sz * (W / 2));
      p.castShadow = true;
      const f = new THREE.Mesh(flag, new THREE.MeshStandardMaterial({ color: "#facc15", side: THREE.DoubleSide }));
      f.position.set(sx * (L / 2) + 0.2, 1.36, sz * (W / 2));
      scene.add(p, f);
    }
}
