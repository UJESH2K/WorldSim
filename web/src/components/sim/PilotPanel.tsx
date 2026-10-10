"use client";

import {
  Armchair,
  ArrowDown,
  DoorOpen,
  ArrowUp,
  ChevronsDown,
  ChevronsUp,
  CloudFog,
  CornerUpLeft,
  CornerUpRight,
  LightbulbOff,
  MoveLeft,
  MoveRight,
  Package,
  RotateCcw,
  RotateCw,
  Sunset,
  TreeDeciduous,
  Truck,
  UserRound,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { ACTION_LABEL } from "@/lib/engine";

const EVENT_ICON: Record<string, LucideIcon> = {
  "worker steps in": UserRound,
  "branch falls": TreeDeciduous,
  "fog rolls in": CloudFog,
  dusk: Sunset,
  "forklift crosses": Truck,
  "pallet falls": Package,
  "lights fail": LightbulbOff,
  "person steps in": UserRound,
  "chair pushed in": Armchair,
  "door swings open": DoorOpen,
  "lights dim": LightbulbOff,
};

// On-screen pad: each button holds the same keys the keyboard would, so both paths share one mapping.
const PAD: { keys: string[]; label: string; icon: LucideIcon; hint: string }[] = [
  { keys: ["w", "arrowleft"], label: "Curve left", icon: CornerUpLeft, hint: "W + ←" },
  { keys: ["w"], label: "Forward", icon: ArrowUp, hint: "W" },
  { keys: ["w", "arrowright"], label: "Curve right", icon: CornerUpRight, hint: "W + →" },
  { keys: ["arrowleft"], label: "Turn left", icon: RotateCcw, hint: "←" },
  { keys: [], label: "", icon: Zap, hint: "" }, // centre: shows the current action
  { keys: ["arrowright"], label: "Turn right", icon: RotateCw, hint: "→" },
  { keys: ["a"], label: "Slide left", icon: MoveLeft, hint: "A" },
  { keys: ["s"], label: "Back", icon: ArrowDown, hint: "S" },
  { keys: ["d"], label: "Slide right", icon: MoveRight, hint: "D" },
];

export function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-grid min-w-6 place-items-center rounded-md border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-2">
      {children}
    </kbd>
  );
}

type Props = {
  flying: boolean;
  autopilot: boolean;
  onAutopilot: (on: boolean) => void;
  press: (keys: string[]) => void;
  release: (keys: string[]) => void;
  currentAction?: string;
  pilot?: string;
  events: string[];
  onEvent: (label: string) => void;
  brain: "reflex" | "learned";
  brainName?: string | null;
  onBrain: (b: "reflex" | "learned") => void;
};

export function PilotPanel(p: Props) {
  const hold = (keys: string[]) => ({
    onPointerDown: (e: React.PointerEvent) => {
      e.preventDefault();
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      p.press(keys);
    },
    onPointerUp: () => p.release(keys),
    onPointerCancel: () => p.release(keys),
    onLostPointerCapture: () => p.release(keys),
    onKeyDown: (e: React.KeyboardEvent) => {
      if ((e.key === "Enter" || e.key === " ") && !e.repeat) {
        e.preventDefault();
        e.stopPropagation();
        p.press(keys);
      }
    },
    onKeyUp: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.stopPropagation();
        p.release(keys);
      }
    },
  });

  return (
    <div className="flex flex-col gap-5">
      <section aria-labelledby="pilot-h" data-tour="pad">
        <h2 id="pilot-h" className="eyebrow">
          Pilot
        </h2>
        <button
          type="button"
          role="switch"
          aria-checked={p.autopilot}
          disabled={!p.flying}
          onClick={() => p.onAutopilot(!p.autopilot)}
          className="mt-3 flex w-full items-center justify-between gap-3 rounded-xl border border-line bg-surface-2 p-3 text-left transition hover:border-line-strong disabled:opacity-50"
        >
          <span>
            <span className="block font-semibold">Autopilot</span>
            <span className="block text-xs text-muted">
              {p.autopilot ? "Lucid is flying. Hold any control to take over." : "You are flying. Space hands back."}
            </span>
          </span>
          <span className={`relative h-6 w-11 shrink-0 rounded-full transition ${p.autopilot ? "bg-accent" : "bg-white/15"}`} aria-hidden>
            <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${p.autopilot ? "left-[22px]" : "left-0.5"}`} />
          </span>
        </button>

        <div className="mt-2">
          <div role="radiogroup" aria-label="Autopilot brain" className="flex rounded-lg bg-surface-2 p-0.5 text-xs">
            {(
              [
                { id: "reflex", label: "Hand-tuned" },
                { id: "learned", label: p.brain === "learned" && p.brainName ? `Learned ${p.brainName}` : "Learned (Lab)" },
              ] as const
            ).map((b) => (
              <button
                key={b.id}
                type="button"
                role="radio"
                aria-checked={p.brain === b.id}
                onClick={() => p.onBrain(b.id)}
                className={`flex-1 rounded-md px-2 py-1.5 transition ${p.brain === b.id ? "bg-surface text-ink ring-1 ring-line" : "text-muted hover:text-ink"}`}
              >
                {b.label}
              </button>
            ))}
          </div>
          <p className="mt-1 text-[11px] text-muted">
            {p.brain === "learned"
              ? "The Pilot Lab's network flies from the camera alone."
              : "Reflex rules on the referee's signals, auto-tunable."}
          </p>
        </div>

        <div className="mx-auto mt-4 grid max-w-[264px] grid-cols-3 gap-1.5 lg:max-w-none" role="group" aria-label="Flight controls (press and hold)">
          {PAD.map((b, i) =>
            b.keys.length === 0 ? (
              <div
                key={i}
                className="grid aspect-square place-items-center rounded-xl border border-dashed border-line text-center"
                aria-live="polite"
              >
                <span className="px-1 text-[11px] leading-tight text-muted">
                  {p.flying ? (
                    <>
                      <span className="block font-semibold text-ink">{ACTION_LABEL[p.currentAction ?? ""] ?? "—"}</span>
                      {p.pilot === "human" ? "you" : p.pilot === "autopilot" ? "autopilot" : "idle"}
                    </>
                  ) : (
                    "start a flight"
                  )}
                </span>
              </div>
            ) : (
              <button
                key={i}
                type="button"
                disabled={!p.flying}
                aria-label={`${b.label} (${b.hint})`}
                className="tip group grid aspect-square touch-none select-none place-items-center rounded-xl border border-line bg-surface-2 text-ink-2 transition hover:border-line-strong hover:text-ink active:scale-95 active:bg-accent active:text-white disabled:opacity-40"
                data-tip={`${b.label} · ${b.hint}`}
                {...hold(b.keys)}
              >
                <b.icon className="h-5 w-5" aria-hidden />
              </button>
            ),
          )}
        </div>
        <div className="mx-auto mt-1.5 grid max-w-[264px] grid-cols-2 gap-1.5 lg:max-w-none">
          {[
            { keys: ["arrowup"], label: "Climb", icon: ChevronsUp, hint: "↑" },
            { keys: ["arrowdown"], label: "Descend", icon: ChevronsDown, hint: "↓" },
          ].map((b) => (
            <button
              key={b.label}
              type="button"
              disabled={!p.flying}
              aria-label={`${b.label} (${b.hint})`}
              className="flex touch-none select-none items-center justify-center gap-1.5 rounded-xl border border-line bg-surface-2 py-2 text-sm text-ink-2 transition hover:border-line-strong hover:text-ink active:bg-accent active:text-white disabled:opacity-40"
              {...hold(b.keys)}
            >
              <b.icon className="h-4 w-4" aria-hidden /> {b.label}
            </button>
          ))}
        </div>
        <p className="mt-3 flex flex-wrap items-center gap-1 text-xs text-muted">
          Keyboard: <Kbd>W</Kbd>
          <Kbd>A</Kbd>
          <Kbd>S</Kbd>
          <Kbd>D</Kbd> move, <Kbd>←</Kbd>
          <Kbd>→</Kbd> turn, <Kbd>Space</Kbd> autopilot
        </p>
      </section>

      <section aria-labelledby="events-h" data-tour="events">
        <h2 id="events-h" className="eyebrow">
          Make something happen
        </h2>
        <p className="mt-1 text-xs text-muted">Changes the world mid-flight, to test the referee.</p>
        <div className="mt-3 grid grid-cols-2 gap-1.5">
          {p.events.map((e) => {
            const Icon = EVENT_ICON[e] ?? Zap;
            return (
              <button
                key={e}
                type="button"
                disabled={!p.flying}
                onClick={() => p.onEvent(e)}
                className="flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-2.5 py-2 text-left text-sm capitalize text-ink-2 transition hover:border-line-strong hover:text-ink disabled:opacity-40"
              >
                <Icon className="h-4 w-4 shrink-0 text-accent" aria-hidden />
                {e}
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}
