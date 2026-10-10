// Plain data shared by server and client components: types, constants and formatting.
// Kept free of React so the server-rendered landing page can import real values.

// JSON goes through the Next rewrite (/engine/* -> engine:8765); the MJPEG stream and frame
// snapshots go straight to the engine so the proxy never buffers video.
export const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://127.0.0.1:8765";
export const STREAM_URL = `${ENGINE_URL}/stream.mjpg`;

import type { LiveAudit } from "./lab";

export type Verdict = "clear" | "caution" | "warning" | "collision" | "anomaly";

export type Hazard = {
  label: string;
  raw: string;
  conf: number;
  box: [number, number, number, number];
  gap: number;
  zone: "touching" | "close" | "ahead" | "behind" | "far";
};

export type Decision = {
  n: number;
  k: number;
  t: number;
  action: string;
  by: "autopilot" | "human" | "idle";
  why: string;
  verdict: Verdict;
  reasons: string[];
  danger: number;
  presence: number;
  obedience: number | null;
  hazards: Hazard[];
  physics?: { speed_ms: number; altitude_m: number; battery_pct: number; heading_deg: number; tilt_deg: number };
};

export type Alert = {
  n: number;
  k: number;
  verdict: Verdict;
  reasons: string[];
  action: string;
  by: string;
  thumb: string;
  narration?: string | null;
};

export type TuneRow = {
  params: { veer: number; spin: number; balance: number; yield_gap: number };
  flights: number;
  score: number;
  forward: number;
  warnings: number;
  collisions: number;
  crashes_truth: number;
};

export type Round = {
  round: number;
  dataset: number;
  val_acc: number | null;
  eval: { collision_rate: number | null; mean_distance_m: number };
  teacher_eval: { collision_rate: number | null; mean_distance_m: number };
};

export type Flight = {
  world: "mock" | "reactor" | null;
  scene: string | null;
  autopilot: boolean;
  manual: string | null;
  decisions: Decision[];
  alerts: Alert[];
  counts: Record<string, number>;
  assessment: { verdict?: Verdict; reasons?: string[]; hazards?: Hazard[]; presence?: number; danger?: number };
  narration: { text: string; ms: number; at: number } | null;
  tune: TuneRow[];
  params: { veer: number; yield_gap: number };
  physics: Partial<Physics>;
  calibration: Calibration;
  report_id: string | null;
  audit?: LiveAudit | null; // world-model audit, LingBot flights only
  brain?: "reflex" | "learned"; // who the autopilot is
  brain_name?: string | null; // the Pilot Lab version flying, when learned
};

/** Live state of the quadrotor physics twin (the source of truth for the drone). */
export type Physics = {
  t: number;
  pos_m: number[];
  speed_ms: number;
  vz_ms: number;
  altitude_m: number;
  heading_deg: number;
  roll_deg: number;
  pitch_deg: number;
  tilt_deg: number;
  motor_rpm: number[];
  power_w: number;
  battery_pct: number;
  energy_wh: number;
  distance_m: number;
  engine: string;
};

export type Calibration = {
  k_yaw?: number;
  yaw_fit_r2?: number;
  speed_tracking_corr?: number;
  yaw_samples?: number;
  k_yaw_saved?: number;
  flights_calibrated?: number;
};

export type ReportCheck = { id: string; requirement: string; value: number | null; threshold: string; pass: boolean | null };

export type Report = {
  id: string;
  at: string;
  world: string;
  scene: { key: string; title: string };
  verdict: "PASS" | "FAIL";
  metrics: Record<string, number | null>;
  checks: ReportCheck[];
  counts: Record<string, number>;
  calibration: Calibration;
  recommendations: string[];
  model: { airframe: string; engine?: string; physics: Record<string, number>; controller: Record<string, number | number[]>; command_profile: Record<string, number>; autopilot: Record<string, number> };
  trace: { n: number; t: number; action: string; by: string; verdict: Verdict; speed_ms: number | null; battery_pct: number | null }[];
  world_audit?: LiveAudit | null; // LingBot flights: where the generated world went wrong
};

export type ReportSummary = { id: string; at: string; world: string; scene: string; verdict: "PASS" | "FAIL"; distance_m: number; collisions: number };

export const WORLD_LABEL: Record<string, string> = { mock: "Practice world", photo: "Practice (your photo)", reactor: "Real AI world" };

export type EngineState = {
  status: string;
  detail: string;
  job: "flight" | "autotune" | "train" | null;
  config: { world?: string; scene?: string; seconds?: number } & Record<string, unknown>;
  log: string[];
  usage: { backend?: string; seconds?: number; usd?: number; cap_seconds?: number };
  rounds: Round[];
  budget: { spent_usd: number; spendable_usd: number; gpu_seconds: number; cap_usd: number };
  model: string | null;
  flight: Flight;
};

export type Catalog = {
  worlds: {
    key: string;
    title: string;
    events: string[];
    drone_box: [number, number, number, number];
    custom: boolean; // uploaded by the user ("Your place")
    thumb: string;
  }[];
  rate_per_second: number;
};

/** What each verdict means, in words a non-engineer can act on. Severity drives tick height,
 *  so the timeline reads without colour as well (dataviz: status never by colour alone). */
export const VERDICTS: Record<Verdict, { label: string; color: string; severity: number; plain: string }> = {
  clear: { label: "Clear", color: "#0ca30c", severity: 1, plain: "Nothing near the drone." },
  caution: { label: "Caution", color: "#fab219", severity: 2, plain: "Something is in view or getting closer." },
  warning: { label: "Warning", color: "#f06a1d", severity: 3, plain: "Something is close or in the flight path." },
  collision: { label: "Collision", color: "#c2253d", severity: 4, plain: "Something is touching the drone." },
  anomaly: { label: "World broke", color: "#9085e9", severity: 4, plain: "The generated world stopped making sense." },
};

export const ACTION_LABEL: Record<string, string> = {
  hover: "Hover",
  forward: "Forward",
  back: "Back",
  left: "Slide left",
  right: "Slide right",
  yaw_left: "Turn left",
  yaw_right: "Turn right",
  arc_left: "Curve left",
  arc_right: "Curve right",
  up: "Climb",
  down: "Descend",
};

export function formatUsd(v: number | undefined) {
  return `$${(v ?? 0).toFixed(2)}`;
}
