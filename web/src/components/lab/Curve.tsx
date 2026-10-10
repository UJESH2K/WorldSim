"use client";

/** One metric across pilot versions. Single series, so the title names it and there is no legend.
 *  Hover is shared between the small multiples (the parent owns `hover`), so pointing at v4 in one
 *  chart shows v4 in all of them. */
export function Curve({
  title,
  help,
  values,
  labels,
  hover,
  onHover,
  best,
  format,
  min,
  max,
  better,
  band,
  formatDelta,
}: {
  title: string;
  help: string;
  values: number[];
  labels: string[];
  hover: number | null;
  onHover: (i: number | null) => void;
  best?: number;
  format: (v: number) => string;
  min?: number;
  max?: number;
  better: "up" | "down";
  band?: number[]; // 0..1 per version, drawn as a faint bar under the axis (the expert co-pilot share)
  formatDelta?: (v: number) => string;
}) {
  const n = values.length;
  const W = 320;
  const H = 120;
  const PAD = { l: 4, r: 4, t: 10, b: 18 };
  const lo = min ?? Math.min(...values);
  const hi = max ?? Math.max(...values);
  const span = hi - lo || 1;
  const x = (i: number) => PAD.l + (n <= 1 ? 0 : (i / (n - 1)) * (W - PAD.l - PAD.r));
  const y = (v: number) => PAD.t + (1 - (v - lo) / span) * (H - PAD.t - PAD.b);
  const shown = hover ?? n - 1;
  const first = values[0];
  const cur = values[shown];
  const delta = n > 1 ? cur - first : 0;
  const improved = better === "down" ? delta < 0 : delta > 0;

  return (
    <figure className="min-w-0 rounded-xl border border-line bg-surface p-4">
      <figcaption>
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="text-sm font-medium text-ink-2">{title}</h3>
          <span className="num text-xs text-muted">{labels[shown]}</span>
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="num text-2xl font-semibold tracking-tight">{n ? format(cur) : "—"}</span>
          {n > 1 && shown > 0 && Math.abs(delta) > 1e-9 && (
            <span className={`num text-xs font-medium ${improved ? "text-clear" : "text-warning"}`}>
              {delta > 0 ? "+" : "−"}
              {(formatDelta ?? format)(Math.abs(delta))} vs v0
            </span>
          )}
        </div>
        <p className="text-[11px] text-muted">{help}</p>
      </figcaption>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="mt-2 h-32 w-full cursor-crosshair overflow-visible"
        role="img"
        aria-label={`${title}: ${labels.map((l, i) => `${l} ${format(values[i])}`).join(", ")}`}
        onMouseMove={(e) => {
          if (n < 2) return;
          const r = e.currentTarget.getBoundingClientRect();
          const rel = (e.clientX - r.left) / r.width;
          onHover(Math.max(0, Math.min(n - 1, Math.round(rel * (n - 1)))));
        }}
        onMouseLeave={() => onHover(null)}
      >
        {[0, 0.5, 1].map((t) => (
          <line key={t} x1={PAD.l} x2={W - PAD.r} y1={PAD.t + t * (H - PAD.t - PAD.b)} y2={PAD.t + t * (H - PAD.t - PAD.b)}
            stroke="var(--line)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        ))}
        {band?.map((b, i) =>
          b > 0 ? (
            <rect key={i} x={x(i) - 5} y={H - PAD.b + 4} width="10" height={8 * b + 1} rx="1.5" fill="var(--anomaly)" opacity="0.55" />
          ) : null,
        )}
        {n > 1 && (
          <polyline
            points={values.map((v, i) => `${x(i)},${y(v)}`).join(" ")}
            fill="none"
            stroke="var(--accent)"
            strokeWidth="2"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        )}
        {values.map((v, i) => (
          <circle key={i} cx={x(i)} cy={y(v)} r={i === shown ? 4.5 : i === best ? 4 : 2.5}
            fill={i === best ? "var(--clear)" : "var(--accent)"} stroke="var(--surface)" strokeWidth="1.5" />
        ))}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.t - 6} y2={H - PAD.b} stroke="var(--line-strong)" strokeWidth="1" />}
        <text x={PAD.l} y={H - 2} fontSize="10" fill="var(--muted)">{labels[0]}</text>
        <text x={W - PAD.r} y={H - 2} fontSize="10" fill="var(--muted)" textAnchor="end">{labels[n - 1]}</text>
      </svg>
    </figure>
  );
}
