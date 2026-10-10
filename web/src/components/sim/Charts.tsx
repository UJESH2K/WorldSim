"use client";

import { useEffect, useRef, useState } from "react";
import { VERDICT_ICON } from "@/components/common";
import { ACTION_LABEL, VERDICTS, type Decision, type Verdict } from "@/lib/engine";

/** One measure over the last N steps. Single series: the title names it, no legend.
 *  Hover (or focus + arrow keys) shows the value at that step. */
export function Trace({
  title,
  help,
  values,
  min = 0,
  max = 1,
  format = (v) => v.toFixed(2),
}: {
  title: string;
  help: string;
  values: number[];
  min?: number;
  max?: number;
  format?: (v: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const n = values.length;
  const W = 200;
  const H = 44;
  const x = (i: number) => (n <= 1 ? W : (i / (n - 1)) * W);
  const y = (v: number) => H - 3 - ((Math.max(min, Math.min(max, v)) - min) / (max - min)) * (H - 6);
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const shown = hover ?? n - 1;
  const value = n ? values[shown] : null;

  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm text-ink-2">{title}</h3>
        <span className="num text-sm font-semibold">{value === null ? "—" : format(value)}</span>
      </div>
      <p className="text-[11px] text-muted">
        {hover !== null ? `${n - 1 - hover} steps ago` : help}
      </p>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="mt-1 h-11 w-full cursor-crosshair overflow-visible"
        tabIndex={n ? 0 : -1}
        role="img"
        aria-label={`${title}: latest ${value === null ? "no data" : format(value)}`}
        onMouseMove={(e) => {
          if (!n) return;
          const r = e.currentTarget.getBoundingClientRect();
          setHover(Math.round(((e.clientX - r.left) / r.width) * (n - 1)));
        }}
        onMouseLeave={() => setHover(null)}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? n - 1) - 1));
          if (e.key === "ArrowRight") setHover((h) => Math.min(n - 1, (h ?? n - 1) + 1));
        }}
        onBlur={() => setHover(null)}
      >
        <line x1="0" y1={H - 0.5} x2={W} y2={H - 0.5} stroke="var(--line-strong)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        {n > 1 && <polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />}
        {n > 0 && (
          <>
            {hover !== null && <line x1={x(shown)} y1="0" x2={x(shown)} y2={H} stroke="var(--line-strong)" strokeWidth="1" vectorEffect="non-scaling-stroke" />}
            <circle cx={x(shown)} cy={y(values[shown])} r="3.5" fill="var(--accent)" stroke="var(--surface)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
          </>
        )}
      </svg>
    </div>
  );
}

const SEVERITY_HEIGHT = { 1: 30, 2: 52, 3: 76, 4: 100 } as const;

/** One mark per decision. Height = severity and colour = verdict, so it reads without colour too. */
export function Timeline({ decisions }: { decisions: Decision[] }) {
  const [hover, setHover] = useState<Decision | null>(null);
  const strip = useRef<HTMLDivElement>(null);
  const [slots, setSlots] = useState(60);
  // As many 4px bars (plus 2px gaps) as fit, so a short flight does not turn into wide blocks.
  useEffect(() => {
    const el = strip.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSlots(Math.max(20, Math.min(160, Math.floor((e.contentRect.width + 2) / 6)))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const shown = decisions.slice(-slots);
  return (
    <div data-tour="timeline">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <h3 className="text-sm text-ink-2">Every decision, newest on the right</h3>
        <ul className="flex flex-wrap items-center gap-3 text-[11px] text-muted" aria-label="Legend">
          {(Object.keys(VERDICTS) as Verdict[]).map((v) => {
            const Icon = VERDICT_ICON[v];
            return (
              <li key={v} className="flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: VERDICTS[v].color }} aria-hidden />
                <Icon className="h-3 w-3" aria-hidden />
                {VERDICTS[v].label}
              </li>
            );
          })}
        </ul>
      </div>
      <div className="relative mt-2">
        <div
          ref={strip}
          className="flex h-14 items-end justify-end gap-[2px] border-b border-line-strong"
          role="img"
          aria-label={`${decisions.length} decisions so far. Latest: ${shown.length ? VERDICTS[shown[shown.length - 1].verdict].label : "none"}.`}
          onMouseLeave={() => setHover(null)}
        >
          {shown.length === 0 && <p className="mr-auto self-center text-xs text-muted">Decisions appear here once the drone is flying.</p>}
          {shown.map((d) => (
            <div
              key={d.n}
              className="flex h-full items-end"
              style={{ flex: `0 0 calc((100% - ${(slots - 1) * 2}px) / ${slots})` }}
              onMouseEnter={() => setHover(d)}
            >
              <div
                className="w-full rounded-t-[3px]"
                style={{
                  height: `${SEVERITY_HEIGHT[VERDICTS[d.verdict].severity as 1 | 2 | 3 | 4]}%`,
                  background: VERDICTS[d.verdict].color,
                  opacity: hover && hover.n !== d.n ? 0.45 : d.by === "human" ? 0.75 : 1,
                }}
              />
            </div>
          ))}
        </div>
        {hover && (
          <div className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 w-72 -translate-x-1/2 rounded-lg border border-line bg-surface p-3 text-xs shadow-xl">
            <div className="flex items-center justify-between">
              <span className="font-semibold" style={{ color: VERDICTS[hover.verdict].color }}>
                {VERDICTS[hover.verdict].label}
              </span>
              <span className="num text-muted">step {hover.n + 1} · {hover.t.toFixed(1)} s</span>
            </div>
            <p className="mt-1 text-ink-2">
              {hover.by === "human" ? "You" : hover.by === "autopilot" ? "Autopilot" : "Idle"}: {ACTION_LABEL[hover.action] ?? hover.action}
              {hover.by === "autopilot" && hover.why ? ` (${hover.why})` : ""}
            </p>
            {hover.reasons.length > 0 && <p className="mt-1 text-muted">{hover.reasons.join("; ")}</p>}
          </div>
        )}
      </div>
    </div>
  );
}

export function StatTile({ label, value, accent }: { label: string; value: string | number; accent?: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-xs text-ink-2">
        {accent && <span className="h-2 w-2 rounded-full" style={{ background: accent }} aria-hidden />}
        {label}
      </div>
      <div className="mt-0.5 text-2xl font-semibold tracking-tight">{value}</div>
    </div>
  );
}
