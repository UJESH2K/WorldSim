"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, CircleCheck, CircleX, Download, Printer } from "lucide-react";
import { Logo, VerdictBadge } from "@/components/common";
import { AUDIT_KIND } from "@/lib/lab";
import { VERDICTS, WORLD_LABEL, type Report, type Verdict } from "@/lib/model";

const METRICS: { key: string; label: string; unit: string; digits?: number }[] = [
  { key: "duration_s", label: "Flight time", unit: "s", digits: 1 },
  { key: "distance_m", label: "Distance flown", unit: "m", digits: 1 },
  { key: "max_speed_ms", label: "Top speed", unit: "m/s", digits: 1 },
  { key: "max_tilt_deg", label: "Max tilt", unit: "°", digits: 1 },
  { key: "energy_wh", label: "Energy used", unit: "Wh", digits: 2 },
  { key: "battery_end_pct", label: "Battery at the end", unit: "%", digits: 1 },
  { key: "decisions", label: "Decisions", unit: "", digits: 0 },
  { key: "decision_rate_hz", label: "Decision rate", unit: "Hz", digits: 2 },
  { key: "collisions", label: "Collisions called", unit: "", digits: 0 },
  { key: "warnings", label: "Warnings", unit: "", digits: 0 },
  { key: "min_separation_m", label: "Closest approach", unit: "m", digits: 2 },
  { key: "human_share", label: "Flown by a person", unit: "%", digits: 0 },
];

function fmt(v: number | null | undefined, digits = 1, pct = false) {
  if (v === null || v === undefined) return "—";
  return (pct ? v * 100 : v).toFixed(digits);
}

function SpeedChart({ trace }: { trace: Report["trace"] }) {
  const pts = trace.filter((t) => t.speed_ms !== null);
  if (pts.length < 2) return null;
  const tMax = pts[pts.length - 1].t || 1;
  const vMax = Math.max(1, ...pts.map((p) => p.speed_ms ?? 0));
  const W = 600, H = 140, L = 34, B = 22;
  const x = (t: number) => L + (t / tMax) * (W - L - 8);
  const y = (v: number) => H - B - (v / vMax) * (H - B - 10);
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Speed over the flight, peaking at ${vMax.toFixed(1)} metres per second`}>
        {[0, vMax / 2, vMax].map((v) => (
          <g key={v}>
            <line x1={L} x2={W - 8} y1={y(v)} y2={y(v)} stroke="var(--line)" />
            <text x={L - 6} y={y(v) + 4} textAnchor="end" className="fill-[var(--muted)] text-[10px]">
              {v.toFixed(1)}
            </text>
          </g>
        ))}
        {/* verdict strip along the bottom: one tick per decision */}
        {trace.map((t, i) => (
          <rect key={i} x={x(t.t)} y={H - B + 6} width={Math.max(1.5, (W - L) / trace.length - 1)} height={6} fill={VERDICTS[t.verdict].color} />
        ))}
        <polyline points={pts.map((p) => `${x(p.t)},${y(p.speed_ms ?? 0)}`).join(" ")} fill="none" stroke="var(--accent)" strokeWidth="2" />
      </svg>
      <figcaption className="mt-1 text-xs text-muted">Speed from the physics (m/s) over {tMax.toFixed(1)} s of flight; the strip below shows the referee&apos;s call at each step.</figcaption>
    </figure>
  );
}

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const [r, setR] = useState<Report | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    fetch(`/engine/reports/${id}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res.status)))
      .then(setR)
      .catch(() => setErr("This report could not be loaded. Is the engine running?"));
  }, [id]);

  if (err) return <p className="p-8 text-collision">{err}</p>;
  if (!r) return <p className="p-8 text-muted">Loading the flight report…</p>;
  const passed = r.verdict === "PASS";

  return (
    <div className="min-h-screen bg-bg print:bg-white">
      <header className="border-b border-line bg-surface print:hidden">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between gap-3 px-4">
          <div className="flex items-center gap-3">
            <Link href="/sim" className="inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-ink">
              <ArrowLeft className="h-4 w-4" /> Simulator
            </Link>
            <Link href="/reports" className="text-sm text-ink-2 hover:text-ink">
              All reports
            </Link>
          </div>
          <div className="flex gap-2">
            <a
              href={`/engine/reports/${r.id}`}
              download={`${r.id}.json`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line-strong px-3 py-1.5 text-sm hover:bg-surface-2"
            >
              <Download className="h-4 w-4" /> JSON
            </a>
            <button onClick={() => window.print()} className="inline-flex items-center gap-1.5 rounded-lg bg-accent-fill px-3 py-1.5 text-sm font-medium text-white hover:opacity-90">
              <Printer className="h-4 w-4" /> Print / PDF
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <Logo className="text-ink" />
            <p className="eyebrow mt-4">Flight report · {r.id}</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight">{r.scene.title}</h1>
            <p className="mt-1 text-ink-2">
              {WORLD_LABEL[r.world] ?? r.world} · {r.at} · {r.model.airframe}
            </p>
          </div>
          <div className={`rounded-2xl px-6 py-4 text-center ${passed ? "bg-clear" : "bg-collision"}`}>
            <div className={`text-xs font-semibold uppercase tracking-wider ${passed ? "text-[#0b0b0b]" : "text-white"}`}>Safety verdict</div>
            <div className={`mt-1 text-4xl font-bold ${passed ? "text-[#0b0b0b]" : "text-white"}`}>{r.verdict}</div>
          </div>
        </div>

        <section className="mt-8">
          <h2 className="text-lg font-semibold">Requirements</h2>
          <ul className="mt-3 divide-y divide-line rounded-xl border border-line bg-surface">
            {r.checks.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-4 px-4 py-3">
                <span className="flex items-center gap-2">
                  {c.pass === null ? (
                    <span className="h-5 w-5 rounded-full border border-line-strong" aria-label="not measured" />
                  ) : c.pass ? (
                    <CircleCheck className="h-5 w-5 text-clear" aria-label="passed" />
                  ) : (
                    <CircleX className="h-5 w-5 text-collision" aria-label="failed" />
                  )}
                  {c.requirement}
                </span>
                <span className="num text-sm text-ink-2">
                  {c.value ?? "not measured"} <span className="text-muted">(needs {c.threshold})</span>
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="mt-8">
          <h2 className="text-lg font-semibold">Flight</h2>
          <dl className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3 lg:grid-cols-4">
            {METRICS.map((m) => (
              <div key={m.key} className="bg-surface p-4">
                <dt className="text-sm text-ink-2">{m.label}</dt>
                <dd className="mt-1 text-2xl font-semibold tracking-tight">
                  {fmt(r.metrics[m.key], m.digits, m.key === "human_share")}
                  <span className="ml-1 text-sm font-normal text-muted">{m.unit}</span>
                </dd>
              </div>
            ))}
          </dl>
          <div className="mt-4 rounded-xl border border-line bg-surface p-4">
            <SpeedChart trace={r.trace} />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {(Object.keys(r.counts) as Verdict[]).map((v) => (
              <span key={v} className="flex items-center gap-1.5 text-sm">
                <VerdictBadge verdict={v} size="sm" /> <span className="num text-ink-2">{r.counts[v]}</span>
              </span>
            ))}
          </div>
        </section>

        {r.world_audit && (
          <section className="mt-8">
            <h2 className="text-lg font-semibold">World audit</h2>
            <p className="mt-1 text-sm text-ink-2">
              {Math.round(r.world_audit.trusted_share * 100)}% of the flight still looked like the seed photo
              {r.world_audit.reanchors ? `; the world was re-anchored ${r.world_audit.reanchors} time${r.world_audit.reanchors > 1 ? "s" : ""} from a trusted frame` : ""}.
            </p>
            {r.world_audit.events.length > 0 && (
              <ul className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {r.world_audit.events.map((e, i) => (
                  <li key={i} className="overflow-hidden rounded-lg border border-line bg-surface">
                    {e.thumb && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={`data:image/jpeg;base64,${e.thumb}`} alt={e.detail} className="aspect-video w-full object-cover" />
                    )}
                    <p className="p-2.5 text-sm">
                      <b className="text-collision">{AUDIT_KIND[e.kind].label}</b> · chunk {e.chunk}: {e.detail}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        <section className="mt-8 grid gap-6 md:grid-cols-2">
          <div>
            <h2 className="text-lg font-semibold">What to change</h2>
            <ul className="mt-3 list-disc space-y-1.5 pl-5 text-ink-2">
              {r.recommendations.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </div>
          <div>
            <h2 className="text-lg font-semibold">Render vs physics calibration</h2>
            <p className="mt-2 text-sm text-ink-2">
              How far the picture turned compared with how far the physics turned (1.00 = they agree). The saved weight is
              updated after every flight and used to drive the world model on the next one.
            </p>
            <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
              <div className="rounded-lg border border-line bg-surface p-3">
                <dt className="text-muted">This flight</dt>
                <dd className="num text-xl font-semibold">{r.calibration.k_yaw?.toFixed(2) ?? "—"}</dd>
                <dd className="text-xs text-muted">fit r² {r.calibration.yaw_fit_r2?.toFixed(2) ?? "—"} · {r.calibration.yaw_samples ?? 0} turns</dd>
              </div>
              <div className="rounded-lg border border-line bg-surface p-3">
                <dt className="text-muted">Saved weight</dt>
                <dd className="num text-xl font-semibold">{r.calibration.k_yaw_saved?.toFixed(2) ?? "—"}</dd>
                <dd className="text-xs text-muted">from {r.calibration.flights_calibrated ?? 0} flights</dd>
              </div>
            </dl>
            {r.calibration.speed_tracking_corr !== undefined && (
              <p className="mt-2 text-xs text-muted">Picture speed follows physics speed with r = {r.calibration.speed_tracking_corr.toFixed(2)}.</p>
            )}
          </div>
        </section>

        <section className="mt-8">
          <h2 className="text-lg font-semibold">Model used</h2>
          <div className="mt-3 grid gap-4 md:grid-cols-3">
            {[
              { title: "Airframe physics", data: r.model.physics },
              { title: "Flight controller gains", data: r.model.controller },
              { title: "Commands", data: { ...r.model.command_profile, ...Object.fromEntries(Object.entries(r.model.autopilot).map(([k, v]) => [`autopilot ${k}`, v])) } },
            ].map((g) => (
              <div key={g.title} className="rounded-xl border border-line bg-surface p-4">
                <h3 className="text-sm font-semibold">{g.title}</h3>
                <dl className="mt-2 space-y-1 text-xs">
                  {Object.entries(g.data).map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-3">
                      <dt className="text-muted">{k.replaceAll("_", " ")}</dt>
                      <dd className="num text-right text-ink-2">{Array.isArray(v) ? v.map((x) => +Number(x).toPrecision(3)).join(", ") : +Number(v).toPrecision(4)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-muted">
            6-DoF quadrotor simulated in {r.model.engine ?? "a Newton–Euler model"} at 400 Hz, with first-order motor lag,
            quadratic drag and a momentum-theory battery model; PX4-style cascaded velocity → attitude → rate control. Collisions are the referee&apos;s reading of the pixels:
            the world model has no geometry to collide with.
          </p>
        </section>
      </main>
    </div>
  );
}
