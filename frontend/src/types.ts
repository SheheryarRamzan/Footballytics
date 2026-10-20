export type Mode = "fan" | "analyst" | "kids" | "audio";
export type View = "matchday" | "centre" | "studio";

export interface Player {
  id: string;
  name: string;
  short_name: string;
  club_id: string;
  group: "GK" | "DEF" | "MID" | "FWD";
  role: string;
  number: number;
  price: number;
  rating: number;
}

export interface Club {
  id: string;
  name: string;
  primary: string;
  secondary: string;
  ground: string;
  style: string;
  formation: string;
  players: Player[];
}

export interface MatchSummary {
  match_id: string;
  home: string;
  away: string;
  home_name: string;
  away_name: string;
  minute: number;
  clock: number;
  score: [number, number];
  status: "PRE" | "LIVE" | "HT" | "FT";
  period: number;
}

/** Compact tracking frame from the wire: players are [id, x, y, km/h]. */
export interface Frame {
  t: number;
  c: number;
  b: [number, number, number];
  o: string | null;
  p: [string, number, number, number][];
}

export interface Moment {
  moment_id: string;
  match_id: string;
  kind: string;
  clock: number;
  minute: number;
  team_id: string | null;
  player_ids: string[];
  facts: Record<string, any>;
  why: string[];
  evidence: string[];
  importance: number;
  caption: { fan: string; analyst: string; kids: string };
  overlay: OverlayCue;
  tags: string[];
}

export interface OverlayCue {
  cue_id: string;
  template: string;
  in_clock: number;
  out_clock: number;
  priority: number;
  anchor: { player_id?: string };
  data: Record<string, any>;
  headline?: string;
  label?: Record<string, string>;
  verified?: boolean;
}

export interface Rendition {
  fan: string;
  analyst: string;
  kids: string;
  audio: string;
  label: string;
}

export interface TraceStep {
  agent: string;
  ms: number;
  note: string;
  attempt?: number;
  issues?: string[];
}

export interface BroadcastItem {
  item_id: string;
  moment_id: string;
  match_id: string;
  kind: string;
  minute: number;
  importance: number;
  status: "verified" | "corrected" | "partially_verified" | "template";
  insight: { headline: string; why_it_matters: string; tactical_angle: string | null };
  renditions: Record<string, Rendition>;
  overlay: OverlayCue;
  claims: { subject_id: string; metric: string; value: number; ok: boolean; actual: number | null }[];
  evidence: string[];
  trace: TraceStep[];
  latency_ms: number;
}

export interface Decision {
  action: "cut" | "pip" | "ticker" | "return" | "points" | "stage";
  match_id: string;
  relevance: number;
  reasons: string[];
  line: string;
  moment_id?: string | null;
  kind?: string | null;
  minute?: number | null;
  data?: Record<string, any>;
  at?: number;
}

export interface SquadPlayer {
  player_id: string;
  name: string;
  short_name: string;
  club: string;
  club_name: string;
  group: string;
  role: string;
  number: number;
  price: number;
  captain: boolean;
  vice_captain: boolean;
}

export interface Taste {
  summary: string;
  more: string[];
  fewer: string[];
  signals: number;
  weights: Record<string, number>;
}

export interface Fan {
  fan_id: string;
  display_name: string;
  favorite_club: string;
  squad: string[];
  captain: string | null;
  vice_captain: string | null;
  mode: Mode;
  language: string;
  focus_player: string | null;
  weights: Record<string, number>;
  squad_detail: SquadPlayer[];
  taste: Taste;
}

export interface TeamStats {
  passes: number;
  pass_completion: number | null;
  shots: number;
  shots_on_target: number;
  big_chances: number;
  goals: number;
  xg: number;
  xt: number;
  possession?: number;
  corners: number;
  fouls: number;
  yellow: number;
  red: number;
  high_turnovers: number;
  distance_km: number;
  tackles_won: number;
  interceptions: number;
}

export interface MatchState {
  match_id: string;
  home: string;
  away: string;
  home_name: string;
  away_name: string;
  minute: number;
  period: number;
  score: Record<string, number>;
  regime: string;
  momentum: { minute: number; value: number }[];
  teams: Record<string, TeamStats>;
  players: Record<string, any>;
  fantasy: Record<string, { points: number; breakdown: any[] }>;
  field_tilt: Record<string, number>;
  home_formation: string;
  away_formation: string;
}

export interface WireEvent {
  event_id: string;
  type: string;
  team_id: string | null;
  player_id: string | null;
  clock: number;
  outcome: string | null;
  x: number | null;
  y: number | null;
  end_x: number | null;
  end_y: number | null;
  qualifiers: Record<string, any>;
}
