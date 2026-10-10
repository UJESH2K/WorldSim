"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Pause, Play, RotateCcw, X } from "lucide-react";
import { ACTION_WORD, STEP_S, type TraceStep } from "@/lib/lab";

type Side = {
  version: string;
  title: string;
  frames: number;
  trace?: TraceStep[];
  crashed: boolean;
  distance?: number;
};

function clearanceColor(c: number) {
  return c < 0.3 ? "var(--collision)" : c < 0.6 ? "var(--warning)" : "var(--clear)";
}

function Player({ runId, scenario, side, t, maxSteps }: { runId: string; scenario: string; side: Side; t: number; maxSteps: number }) {
  const k = Math.max(1, Math.min(t, side.frames));
  const over = t > side.frames;
  const step = side.trace?.[k - 1];
  const crashedNow = side.crashed && k === side.frames;
  const src = `/engine/lab/runs/${runId}/frame/${side.version}/${scenario}/${String(k).padStart(3, "0")}.jpg`;
  return (
    <div className="min-w-0">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{side.title}</h3>
        <span className="num text-xs text-muted">
          {side.crashed ? `crashed at ${(side.frames * STEP_S).toFixed(1)} s` : `flew the full ${(maxSteps * STEP_S).toFixed(0)} s`}
          {side.distance != null ? ` · ${side.distance} m` : ""}
        </span>
      </div>
      <div
        className={`relative aspect-video overflow-hidden rounded-lg bg-black ring-2 transition ${
          crashedNow ? "ring-collision" : "ring-transparent"
        }`}
      >
        {side.frames > 0 ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} alt={`${side.title}, step ${k}`} className={`h-full w-full object-cover ${over ? "opacity-60" : ""}`} />
        ) : (
          <div className="grid h-full place-items-center text-sm text-muted">No replay recorded</div>
        )}
        {crashedNow && (
          <div className="absolute inset-0 grid place-items-center">
            <span className="rounded-md bg-collision px-3 py-1.5 text-sm font-bold uppercase tracking-wide text-white shadow-lg">
              Crash
            </span>
          </div>
        )}
        {!side.crashed && over && (
          <div className="absolute inset-0 grid place-items-center">
            <span className="rounded-md bg-clear px-3 py-1.5 text-sm font-bold uppercase tracking-wide text-[#0b0b0b] shadow-lg">
              Completed
            </span>
          </div>
        )}
        <span className="num absolute left-2 top-2 rounded bg-black/60 px-1.5 py-0.5 text-[11px] text-white">
          {(k * STEP_S).toFixed(2)} s
        </span>
      </div>
      {step && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span>
            <span className="text-muted">Pilot:</span> <span className="font-medium">{ACTION_WORD[step.a] ?? step.a}</span>
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="text-muted">Expert:</span> <span className="font-medium">{ACTION_WORD[step.e] ?? step.e}</span>
            {step.a === step.e ? (
              <Check className="h-3.5 w-3.5 text-clear" aria-label="agrees" />
            ) : (
              <X className="h-3.5 w-3.5 text-warning" aria-label="disagrees" />
            )}
          </span>
          <span className="num ml-auto inline-flex items-center gap-1.5">
            <span className="text-muted">Clearance</span>
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: clearanceColor(step.c) }} aria-hidden />
            <span className="font-medium">{step.c.toFixed(2)} m</span>
          </span>
        </div>
      )}
    </div>
  );
}

/** The same held-out flight, flown by the pilot before and after the Lab, stepped together.
 *  Remount (key) per flight to restart playback. */
export function Replay({ runId, scenario, before, after, maxSteps }: { runId: string; scenario: string; before: Side; after: Side; maxSteps: number }) {
  const total = Math.max(before.frames, after.frames) + 4; // a beat after the end to show the outcome
  const [t, setT] = useState(1);
  const [playing, setPlaying] = useState(true);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Warm the cache so playback does not stutter.
    for (const s of [before, after])
      for (let k = 1; k <= s.frames; k++) {
        const im = new Image();
        im.src = `/engine/lab/runs/${runId}/frame/${s.version}/${scenario}/${String(k).padStart(3, "0")}.jpg`;
      }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, scenario, before.version, after.version]);

  useEffect(() => {
    if (!playing) return;
    timer.current = setInterval(() => setT((v) => (v >= total ? 1 : v + 1)), STEP_S * 1000);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [playing, total]);

  return (
    <div>
      <div className="grid gap-4 md:grid-cols-2">
        <Player runId={runId} scenario={scenario} side={before} t={t} maxSteps={maxSteps} />
        <Player runId={runId} scenario={scenario} side={after} t={t} maxSteps={maxSteps} />
      </div>
      <div className="mt-3 flex items-center gap-3">
        <button
          onClick={() => setPlaying((p) => !p)}
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-line bg-surface-2 hover:border-line-strong"
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
        </button>
        <button
          onClick={() => {
            setT(1);
            setPlaying(true);
          }}
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-line bg-surface-2 hover:border-line-strong"
          aria-label="Restart"
        >
          <RotateCcw className="h-4 w-4" />
        </button>
        <input
          type="range"
          min={1}
          max={total}
          value={t}
          onChange={(e) => {
            setPlaying(false);
            setT(Number(e.target.value));
          }}
          className="h-1.5 flex-1 accent-[var(--accent)]"
          aria-label="Replay position"
        />
        <span className="num w-14 text-right text-xs text-muted">{(Math.min(t, total - 4) * STEP_S).toFixed(1)} s</span>
      </div>
    </div>
  );
}
