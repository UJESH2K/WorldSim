// Pilot Lab and world-model audit: shapes returned by the engine (lucid/lab/api.py).

export type LabRow = {
  version: string;
  crash_rate: number;
  mean_distance_m: number;
  near_miss_steps: number;
  min_clearance_m: number;
  expert_agreement: number;
  success_rate: number;
  iteration: number;
  seconds?: number;
  beta?: number;
  train_crash_rate?: number;
  states?: number;
  dataset?: number;
  mistakes?: number;
  loss_imitation?: number;
  loss_rl?: number;
  loss_value?: number;
};

export type Scenario = {
  id: string;
  seed: number;
  world: string;
  palette: string;
  density: number;
  event_at: number | null;
  profile?: string;
};

export type Mistake = {
  scenario: string;
  step: number;
  kind: "crash" | "near miss";
  clearance: number;
  pilot: string;
  expert: string;
  thumb: string;
  fixed: boolean;
  after_thumb: string | null;
  after_crashed: boolean;
  after_distance: number;
};

export type TraceStep = { a: string; e: string; c: number };

export type EpisodeSummary = {
  crashed: boolean;
  distance: number;
  near: number;
  min_clearance: number;
  agreement: number;
  length: number;
  scenario: Scenario;
};

export type LabRun = {
  id: string;
  base: string;
  base_meta?: { name?: string; trained_on?: string; demonstrations?: number; flights?: number };
  rows: LabRow[];
  final: {
    best: string;
    fixed: Mistake[];
    replays: string[];
    replay_traces?: Record<string, Record<string, { trace: TraceStep[]; crashed: boolean; length: number; distance: number }>>;
    model_file?: string;
  } | null;
  episodes_before: EpisodeSummary[] | null;
  episodes_after: EpisodeSummary[] | null;
  max_steps: number;
  status: "running" | "done" | "stopped" | "error" | "incomplete";
  progress: { stage?: string; iteration?: number; iterations?: number; log?: string[]; status?: string; episodes?: number };
  frames: Record<string, Record<string, number>>;
};

export type LabRunSummary = {
  id: string;
  base: string;
  base_name?: string;
  status: LabRun["status"];
  versions: number;
  best: string | null;
  before: LabRow | null;
  after: LabRow | null;
  updated?: string;
};

export type PilotInfo = {
  file: string;
  name: string;
  trained_on?: string;
  source: "factory" | "upload" | "lab";
  at: string;
  scores?: Record<string, LabRow>;
};

export const STEP_S = 0.25; // one pilot decision

export const PALETTE_LABEL: Record<string, string> = { forest: "daylight", warehouse: "warehouse light", night: "night" };

export function describeScenario(s: Scenario): string {
  const place = s.world === "warehouse" ? "Warehouse aisle" : "Forest";
  const look = PALETTE_LABEL[s.palette] ?? s.palette;
  const clutter = s.density >= 7 ? "dense" : s.density >= 5.5 ? "cluttered" : "sparse";
  const event = s.event_at != null ? ` · someone steps in at ${(s.event_at * STEP_S).toFixed(1)} s` : "";
  return `${place} · ${look} · ${clutter}${event}`;
}

export const ACTION_WORD: Record<string, string> = {
  forward: "forward",
  back: "back up",
  arc_left: "curve left",
  arc_right: "curve right",
  yaw_left: "turn left",
  yaw_right: "turn right",
  hover: "hover",
  left: "slide left",
  right: "slide right",
  up: "climb",
  down: "descend",
};

// ---------------------------------------------------------------- world-model audit
export type AuditEvent = {
  chunk: number;
  kind: "scene drift" | "scene cut" | "colour shift" | "drone morphed" | "pop-in";
  value: number;
  detail: string;
  box: number[] | null;
  thumb: string | null;
};

export type AuditReading = {
  chunk: number;
  scene: number;
  continuity: number | null;
  colour: number;
  drone_scale: number;
  drone_match: number;
  trusted: boolean;
  events: Omit<AuditEvent, "thumb">[];
};

export type AuditSummary = {
  run: string;
  episode: string;
  scene: string;
  world: string;
  chunks: number;
  trusted_share: number;
  counts: Record<string, number>;
  first_failure: number | null;
  reanchors: number;
};

export type Audit = AuditSummary & {
  readings: AuditReading[];
  events: AuditEvent[];
  anchors?: { chunk: number; from_chunk: number }[];
  thresholds?: { scene_min: number; cut_min: number; colour_max: number; drone_min: number };
};

/** Live audit, as part of /state during a LingBot flight. */
export type LiveAudit = {
  chunks: number;
  trusted_share: number;
  counts: Record<string, number>;
  first_failure: number | null;
  reanchors: number;
  latest: AuditReading | null;
  anchors: { chunk: number; from_chunk: number }[];
  series: { k: number; scene: number; drone: number; colour: number; ok: boolean }[];
  events: AuditEvent[];
  thresholds?: Audit["thresholds"];
};

export const AUDIT_KIND: Record<AuditEvent["kind"], { label: string; help: string }> = {
  "scene drift": { label: "Scene drift", help: "The place stopped looking like your photo" },
  "scene cut": { label: "Scene cut", help: "The world jumped to a different place between two moments" },
  "colour shift": { label: "Colour shift", help: "Lighting or white balance wandered away from the photo" },
  "drone morphed": { label: "Drone morphed", help: "The drone grew, stretched or stopped looking like itself" },
  "pop-in": { label: "Pop-in", help: "An obstacle appeared mid-frame without being asked for" },
};

export const THRESHOLDS = { scene_min: 0.8, cut_min: 0.7, colour_max: 20, drone_min: 0.78 };
