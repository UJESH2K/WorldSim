"use client";

import { useState } from "react";
import { CircleCheck, CircleX } from "lucide-react";
import { ACTION_WORD, STEP_S, type Mistake } from "@/lib/lab";

const FILTERS = ["all", "fixed", "not fixed"] as const;

export function Mistakes({ items, bestLabel, onReplay, replayable }: {
  items: Mistake[];
  bestLabel: string;
  onReplay?: (scenario: string) => void;
  replayable?: string[];
}) {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const fixed = items.filter((m) => m.fixed).length;
  const shown = items.filter((m) => filter === "all" || (filter === "fixed") === m.fixed);
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-2">
          <span className="num font-semibold text-ink">{fixed}</span> of <span className="num">{items.length}</span> mistakes the
          imported pilot made on the benchmark no longer happen with {bestLabel}.
        </p>
        <div role="radiogroup" aria-label="Show" className="flex rounded-lg bg-surface-2 p-0.5 text-sm">
          {FILTERS.map((f) => (
            <button
              key={f}
              role="radio"
              aria-checked={filter === f}
              onClick={() => setFilter(f)}
              className={`rounded-md px-3 py-1 capitalize ${filter === f ? "bg-surface text-ink ring-1 ring-line" : "text-muted hover:text-ink"}`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>
      <ul className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {shown.map((m, i) => (
          <li key={`${m.scenario}-${m.step}-${i}`} className="overflow-hidden rounded-xl border border-line bg-surface">
            <div className="grid grid-cols-2 gap-px bg-line">
              <figure className="relative bg-black">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={`data:image/jpeg;base64,${m.thumb}`} alt={`Before: ${m.kind} at ${(m.step * STEP_S).toFixed(1)} s`} className="aspect-video w-full object-cover" />
                <figcaption className="absolute left-1.5 top-1.5 rounded bg-black/65 px-1.5 py-0.5 text-[10px] font-medium text-white">Before</figcaption>
              </figure>
              <figure className="relative bg-black">
                {m.after_thumb ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={`data:image/jpeg;base64,${m.after_thumb}`} alt="After, same moment" className="aspect-video w-full object-cover" />
                ) : (
                  <div className="grid aspect-video place-items-center px-2 text-center text-[11px] text-ink-2">
                    {m.fixed ? "No close call at this moment" : m.after_crashed ? "Crashed elsewhere on this flight" : "—"}
                  </div>
                )}
                <figcaption className="absolute left-1.5 top-1.5 rounded bg-black/65 px-1.5 py-0.5 text-[10px] font-medium text-white">After</figcaption>
              </figure>
            </div>
            <div className="p-3">
              <div className="flex items-center justify-between gap-2">
                <span className={`text-xs font-semibold uppercase tracking-wide ${m.kind === "crash" ? "text-collision" : "text-warning"}`}>
                  {m.kind} · {(m.step * STEP_S).toFixed(1)} s
                </span>
                {m.fixed ? (
                  <span className="inline-flex items-center gap-1 text-xs font-semibold text-clear">
                    <CircleCheck className="h-3.5 w-3.5" aria-hidden /> Fixed
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-xs font-semibold text-ink-2">
                    <CircleX className="h-3.5 w-3.5" aria-hidden /> Not yet
                  </span>
                )}
              </div>
              <p className="mt-1.5 text-sm">
                Chose <b>{ACTION_WORD[m.pilot] ?? m.pilot}</b>; the expert would <b>{ACTION_WORD[m.expert] ?? m.expert}</b>
                <span className="num text-muted"> · {m.clearance.toFixed(2)} m clear</span>
              </p>
              {onReplay && replayable?.includes(m.scenario) && (
                <button onClick={() => onReplay(m.scenario)} className="mt-2 text-xs font-medium text-accent hover:underline">
                  Watch this flight before and after
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
