import { create } from "zustand";
import type {
  BroadcastItem,
  Club,
  Decision,
  Fan,
  Frame,
  MatchSummary,
  Mode,
  Moment,
  Player,
  View,
  WireEvent,
} from "./types";

/** Tracking frames change 20-30 times a second, so they live outside React state. */
export const liveFrames: { prev: Frame | null; cur: Frame | null; prevAt: number; curAt: number; match: string | null } = {
  prev: null,
  cur: null,
  prevAt: 0,
  curAt: 0,
  match: null,
};

export interface FeedEntry {
  key: string;
  at: number;
  match_id: string;
  moment?: Moment;
  decision?: Decision;
  item?: BroadcastItem;
}

export interface ActiveOverlay {
  key: string;
  template: string;
  until: number;
  moment: Moment;
  item?: BroadcastItem;
}

interface State {
  connected: boolean;
  matchday: number | null;
  speed: number;
  clubs: Record<string, Club>;
  players: Record<string, Player>;
  matches: Record<string, MatchSummary>;
  order: string[];
  stage: string | null;
  fan: Fan | null;
  view: View;
  pitch: "3d" | "2d";
  camera: "broadcast" | "player" | "tactical";
  moments: Moment[];
  items: Record<string, BroadcastItem>;
  feed: FeedEntry[];
  overlays: ActiveOverlay[];
  pip: Decision | null;
  events: WireEvent[];
  toast: string | null;
  pointsLive: number;

  setLeague: (clubs: Club[]) => void;
  setFan: (fan: Fan | null) => void;
  setView: (v: View) => void;
  setPitch: (p: "3d" | "2d") => void;
  setCamera: (c: "broadcast" | "player" | "tactical") => void;
  setStage: (id: string) => void;
  showToast: (msg: string) => void;
  dismissFeed: (key: string) => void;
}

export const useStore = create<State>((set) => ({
  connected: false,
  matchday: null,
  speed: 4,
  clubs: {},
  players: {},
  matches: {},
  order: [],
  stage: null,
  fan: null,
  view: "matchday",
  pitch: "3d",
  camera: "broadcast",
  moments: [],
  items: {},
  feed: [],
  overlays: [],
  pip: null,
  events: [],
  toast: null,
  pointsLive: 0,

  setLeague: (clubs) => {
    const c: Record<string, Club> = {};
    const p: Record<string, Player> = {};
    for (const club of clubs) {
      c[club.id] = club;
      for (const pl of club.players) p[pl.id] = pl;
    }
    set({ clubs: c, players: p });
  },
  setFan: (fan) =>
    set((s) => ({
      fan,
      pitch: fan?.mode === "analyst" ? "2d" : s.pitch,
    })),
  setView: (view) => set({ view }),
  setPitch: (pitch) => set({ pitch }),
  setCamera: (camera) => set({ camera }),
  setStage: (id) => {
    set({ stage: id, overlays: [], events: [] });
    liveFrames.prev = liveFrames.cur = null;
    liveFrames.match = id;
    live.send({ stage: id, focus: id });
  },
  showToast: (msg) => {
    set({ toast: msg });
    window.setTimeout(() => set((s) => (s.toast === msg ? { toast: null } : {})), 3500);
  },
  dismissFeed: (key) => set((s) => ({ feed: s.feed.filter((f) => f.key !== key) })),
}));

const OVERLAY_SECONDS: Record<string, number> = {
  goal_card: 9,
  shot_card: 6.5,
  pass_arc: 5.5,
  player_tag: 5,
  stat_bubble: 5,
  lower_third: 6.5,
  momentum_ribbon: 6,
  full_screen: 8,
};

function addFeed(entry: FeedEntry) {
  useStore.setState((s) => {
    const idx = s.feed.findIndex((f) => f.key === entry.key);
    let feed: FeedEntry[];
    if (idx >= 0) {
      feed = [...s.feed];
      feed[idx] = { ...feed[idx], ...entry, at: feed[idx].at };
    } else {
      feed = [entry, ...s.feed].slice(0, 80);
    }
    return { feed };
  });
}

function handle(msg: any) {
  const s = useStore.getState();
  switch (msg.kind) {
    case "hello": {
      const matches: Record<string, MatchSummary> = {};
      for (const m of msg.data.matches as MatchSummary[]) matches[m.match_id] = m;
      useStore.setState({ matchday: msg.data.matchday, speed: msg.data.speed, matches, order: Object.keys(matches) });
      if (!s.fan && !s.stage && msg.data.matches.length) {
        useStore.getState().setStage(msg.data.matches[0].match_id);
      }
      break;
    }
    case "tick": {
      const matches = { ...s.matches };
      for (const m of msg.data as MatchSummary[]) matches[m.match_id] = m;
      useStore.setState({ matches, order: s.order.length ? s.order : Object.keys(matches) });
      break;
    }
    case "frame": {
      if (msg.match_id !== s.stage) break;
      liveFrames.prev = liveFrames.cur;
      liveFrames.prevAt = liveFrames.curAt;
      liveFrames.cur = msg.data as Frame;
      liveFrames.curAt = performance.now();
      liveFrames.match = msg.match_id;
      break;
    }
    case "event": {
      if (msg.match_id !== s.stage) break;
      useStore.setState({ events: [msg.data as WireEvent, ...s.events].slice(0, 60) });
      break;
    }
    case "moment": {
      const m = msg.data as Moment;
      useStore.setState({ moments: [m, ...s.moments].slice(0, 400) });
      if (m.match_id === s.stage && m.importance >= 28 && m.kind !== "kick_off") {
        const secs = OVERLAY_SECONDS[m.overlay.template] ?? 6;
        const ov: ActiveOverlay = { key: m.moment_id, template: m.overlay.template, until: performance.now() + secs * 1000, moment: m };
        useStore.setState((st) => ({ overlays: [...st.overlays.filter((o) => o.until > performance.now()), ov].slice(-4) }));
      }
      if (!s.fan && m.match_id === s.stage && m.importance >= 40) {
        addFeed({ key: m.moment_id, at: Date.now(), match_id: m.match_id, moment: m });
      }
      break;
    }
    case "broadcast": {
      const it = msg.data as BroadcastItem;
      useStore.setState((st) => ({ items: { ...st.items, [it.moment_id]: it } }));
      useStore.setState((st) => ({
        overlays: st.overlays.map((o) =>
          o.key === it.moment_id ? { ...o, item: it, until: Math.max(o.until, performance.now() + 6500) } : o,
        ),
      }));
      const existing = useStore.getState().feed.find((f) => f.key === it.moment_id);
      if (existing) addFeed({ ...existing, item: it });
      else if (it.match_id === useStore.getState().stage) {
        addFeed({ key: it.moment_id, at: Date.now(), match_id: it.match_id, item: it });
      }
      break;
    }
    case "director": {
      const d = { ...(msg.data as Decision), at: Date.now() };
      if (d.action === "stage" || d.action === "cut" || d.action === "return") {
        if (d.match_id && d.match_id !== useStore.getState().stage) {
          useStore.setState({ stage: d.match_id, overlays: [], events: [] });
          liveFrames.prev = liveFrames.cur = null;
          liveFrames.match = d.match_id;
        }
        if (d.action === "cut") useStore.getState().showToast(`Cutting to ${matchLabel(d.match_id)}: ${d.line}`);
      }
      if (d.action === "pip") {
        useStore.setState({ pip: d });
        window.setTimeout(() => {
          if (useStore.getState().pip === d) useStore.setState({ pip: null });
        }, 9000);
      }
      if (d.action === "points") {
        useStore.setState((st) => ({ pointsLive: st.pointsLive + (d.data?.points ?? 0) }));
        addFeed({ key: `pts-${d.data?.event_id ?? Math.random()}-${d.data?.player_id}`, at: Date.now(), match_id: d.match_id, decision: d });
        break;
      }
      if (d.action === "return") break;
      const moment = useStore.getState().moments.find((m) => m.moment_id === d.moment_id);
      if (d.moment_id && (d.action !== "ticker" || d.relevance >= 0.42)) {
        addFeed({
          key: d.moment_id,
          at: Date.now(),
          match_id: d.match_id,
          decision: d,
          moment,
          item: useStore.getState().items[d.moment_id],
        });
      }
      break;
    }
    case "error":
      useStore.getState().showToast(msg.data.message);
      break;
  }
}

export function matchLabel(id: string): string {
  const m = useStore.getState().matches[id];
  if (!m) return id;
  return `${m.home} ${m.score[0]}-${m.score[1]} ${m.away}`;
}

/** WebSocket manager with automatic reconnect; re-sends identity and stage after reconnecting. */
export const live = {
  ws: null as WebSocket | null,
  queue: [] as object[],
  connect() {
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return; // StrictMode double-invoke guard
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws = ws;
    ws.onopen = () => {
      useStore.setState({ connected: true });
      const { fan, stage } = useStore.getState();
      if (fan) this.send({ fan_id: fan.fan_id, languages: [fan.language] });
      else if (stage) this.send({ focus: stage });
      for (const m of this.queue.splice(0)) ws.send(JSON.stringify(m));
    };
    ws.onmessage = (ev) => handle(JSON.parse(ev.data));
    ws.onclose = () => {
      useStore.setState({ connected: false });
      window.setTimeout(() => this.connect(), 1500);
    };
  },
  send(msg: object) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
    else this.queue.push(msg);
  },
};

export function modeText(mode: Mode, r?: { fan: string; analyst: string; kids: string; audio?: string }): string {
  if (!r) return "";
  if (mode === "analyst") return r.analyst;
  if (mode === "kids") return r.kids;
  if (mode === "audio") return r.audio ?? r.fan;
  return r.fan;
}
