"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Atom, FlaskConical, Globe, MessageSquareText, ShieldCheck, SlidersHorizontal, TriangleAlert } from "lucide-react";
import { VerdictBadge } from "@/components/common";
import { ACTION_LABEL, VERDICTS, type EngineState, type Verdict } from "@/lib/engine";
import { Trace } from "./Charts";
import { PhysicsPanel } from "./PhysicsPanel";
import { AUDIT_KIND, THRESHOLDS, type LabRunSummary } from "@/lib/lab";

export type Tab = "safety" | "calls" | "world" | "physics" | "lab";

type Props = {
  tab: Tab;
  setTab: (t: Tab) => void;
  state: EngineState | null;
  busy: boolean;
  world: string;
  rate: number;
  onAutotune: () => void;
};

const TABS: { id: Tab; label: string; icon: typeof ShieldCheck }[] = [
  { id: "safety", label: "Safety", icon: ShieldCheck },
  { id: "calls", label: "Calls", icon: TriangleAlert },
  { id: "world", label: "World", icon: Globe },
  { id: "physics", label: "Physics", icon: Atom },
  { id: "lab", label: "Lab", icon: FlaskConical },
];

export function InsightPanel(p: Props) {
  const f = p.state?.flight;
  const decisions = f?.decisions ?? [];
  const verdict: Verdict = (f?.assessment?.verdict as Verdict) ?? "clear";
  const flying = p.state?.job === "flight";
  const alerts = f?.alerts ?? [];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div role="tablist" aria-label="Insights" className="flex gap-1 rounded-lg bg-surface-2 p-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={p.tab === t.id}
            aria-controls={`panel-${t.id}`}
            onClick={() => p.setTab(t.id)}
            className={`flex min-w-0 flex-1 items-center justify-center gap-1 rounded-md px-1 py-1.5 text-[13px] transition ${
              p.tab === t.id ? "bg-surface text-ink shadow-sm ring-1 ring-line" : "text-muted hover:text-ink"
            }`}
          >
            <t.icon className="hidden h-4 w-4 2xl:block" aria-hidden />
            {t.label}
            {t.id === "calls" && alerts.length > 0 && (
              <span className="num rounded-full bg-collision px-1.5 text-[10px] font-semibold text-white">{alerts.length}</span>
            )}
          </button>
        ))}
      </div>

      <div className="mt-4 min-h-0 flex-1 overflow-y-auto pr-1">
        {p.tab === "safety" && (
          <div id="panel-safety" role="tabpanel" aria-labelledby="tab-safety" className="flex flex-col gap-5" data-tour="safety">
            <section className="rounded-xl border border-line bg-surface p-4">
              <h2 className="eyebrow">Referee&apos;s call right now</h2>
              <div className="mt-3">
                <VerdictBadge verdict={flying ? verdict : "clear"} size="lg" className={flying ? "" : "opacity-40"} />
              </div>
              <p className="mt-3 text-sm leading-relaxed text-ink-2">
                {flying ? VERDICTS[verdict].plain : "Start a flight and the referee will judge every step here."}
              </p>
              {flying && (f?.assessment?.reasons?.length ?? 0) > 0 && (
                <ul className="mt-2 list-disc pl-5 text-sm text-ink">
                  {f!.assessment.reasons!.map((r, i) => (
                    <li key={`${i}-${r}`}>{r}</li>
                  ))}
                </ul>
              )}
            </section>

            <section aria-labelledby="signals-h">
              <h2 id="signals-h" className="eyebrow">
                What the referee is measuring
              </h2>
              <div className="mt-3 flex flex-col gap-4">
                <Trace
                  title="Something getting closer"
                  help="Motion that swells in front of the drone"
                  values={decisions.slice(-80).map((d) => d.danger)}
                  max={0.8}
                />
                <Trace
                  title="Drone looks like the drone"
                  help="1.0 = matches the start; low = the world broke"
                  values={decisions.slice(-80).map((d) => d.presence)}
                />
                <Trace
                  title="World follows the controls"
                  help="+1 = moves as commanded, −1 = the opposite"
                  values={decisions.slice(-80).map((d) => d.obedience ?? 0)}
                  min={-1}
                  max={1}
                  format={(v) => (v >= 0 ? "+" : "") + v.toFixed(2)}
                />
              </div>
            </section>

            <section className="rounded-xl border border-line bg-surface p-4">
              <h2 className="eyebrow flex items-center gap-1.5">
                <MessageSquareText className="h-3.5 w-3.5" aria-hidden /> Narrator · local AI
              </h2>
              <p className="mt-2 text-sm italic leading-relaxed text-ink">
                {f?.narration?.text && !f.narration.text.startsWith("narrator unavailable")
                  ? `“${f.narration.text}”`
                  : flying
                    ? "Warming up… the first description takes a few seconds."
                    : "Describes the scene in plain words during a flight."}
              </p>
              <p className="mt-2 text-[11px] text-muted">Runs on this laptop. It describes; it never decides.</p>
            </section>
          </div>
        )}

        {p.tab === "calls" && (
          <div id="panel-calls" role="tabpanel" aria-labelledby="tab-calls" className="flex flex-col gap-3">
            {alerts.length === 0 && (
              <div className="rounded-xl border border-dashed border-line p-6 text-center text-sm text-muted">
                No warnings yet. During a flight, try <em>worker steps in</em> on the left.
              </div>
            )}
            {alerts
              .slice()
              .reverse()
              .map((a) => (
                <article key={a.n} className="overflow-hidden rounded-xl border border-line bg-surface">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={`data:image/jpeg;base64,${a.thumb}`} alt={a.reasons[0] ?? VERDICTS[a.verdict].label} className="w-full" />
                  <div className="p-3">
                    <div className="flex items-center justify-between gap-2">
                      <VerdictBadge verdict={a.verdict} size="sm" />
                      <span className="num text-[11px] text-muted">step {a.n}</span>
                    </div>
                    <p className="mt-2 text-sm">{a.reasons.join("; ")}</p>
                    <p className="mt-1 text-xs text-muted">
                      {a.by === "human" ? "You" : a.by === "autopilot" ? "Autopilot" : "Drone"} → {ACTION_LABEL[a.action] ?? a.action}
                    </p>
                  </div>
                </article>
              ))}
          </div>
        )}

        {p.tab === "world" && <WorldPanel state={p.state} />}

        {p.tab === "physics" && <PhysicsPanel flight={f} flying={flying} />}

        {p.tab === "lab" && (
          <div id="panel-lab" role="tabpanel" aria-labelledby="tab-lab" className="flex flex-col gap-5">
            <section className="rounded-xl border border-line bg-surface p-4">
              <h2 className="flex items-center gap-2 font-semibold">
                <SlidersHorizontal className="h-4 w-4 text-accent" aria-hidden /> Auto-tune the autopilot
              </h2>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-2">
                Tries six autopilot settings on the same short flights and keeps the one that covers the most ground with the
                fewest referee calls.
              </p>
              <button
                onClick={p.onAutotune}
                disabled={p.busy}
                className="mt-3 w-full rounded-lg bg-accent-fill px-3 py-2 text-sm font-medium text-white transition hover:opacity-90 disabled:opacity-40"
              >
                {p.world === "reactor" ? `Auto-tune in the real AI world (up to $${(240 * p.rate).toFixed(2)})` : "Auto-tune in the practice world (free)"}
              </button>
              {(f?.tune?.length ?? 0) > 0 && (
                <table className="mt-4 w-full text-left text-xs">
                  <caption className="sr-only">Auto-tune results</caption>
                  <thead className="text-muted">
                    <tr className="border-b border-line">
                      <th className="py-1.5 font-normal">Sensitivity</th>
                      <th className="font-normal">Yield gap</th>
                      <th className="text-right font-normal">Distance m</th>
                      <th className="text-right font-normal">Calls</th>
                      <th className="text-right font-normal">Score</th>
                    </tr>
                  </thead>
                  <tbody className="num">
                    {(() => {
                      const best = Math.max(...f!.tune.map((r) => r.score));
                      return f!.tune.map((r, i) => (
                        <tr key={i} className={`border-b border-line ${r.score === best ? "font-semibold text-ink" : "text-ink-2"}`}>
                          <td className="py-1.5">{r.params.veer}</td>
                          <td>{r.params.yield_gap}</td>
                          <td className="text-right">{r.forward}</td>
                          <td className="text-right">{r.warnings + r.collisions + r.crashes_truth}</td>
                          <td className="text-right">
                            {r.score}
                            {r.score === best ? " ★" : ""}
                          </td>
                        </tr>
                      ));
                    })()}
                  </tbody>
                </table>
              )}
              <p className="mt-2 text-[11px] text-muted">
                In use now: sensitivity {f?.params.veer ?? "—"}, yields to people within {f?.params.yield_gap ?? "—"} drone-widths.
              </p>
            </section>

            <LabCard />
          </div>
        )}
      </div>
    </div>
  );
}

/** Live world-model audit (LingBot flights): is the generated world still the place you seeded? */
function WorldPanel({ state }: { state: EngineState | null }) {
  const a = state?.flight?.audit;
  if (!a) {
    return (
      <div id="panel-world" role="tabpanel" aria-labelledby="tab-world" className="flex flex-col gap-4">
        <div className="rounded-xl border border-dashed border-line p-5 text-sm text-ink-2">
          <p>
            In the real AI world, every moment is checked against your photo: does the place still look like it, does the drone
            still look like itself, did anything appear that nobody asked for. When the world drifts, it is restarted from the
            last frame it trusted.
          </p>
          <p className="mt-2 text-muted">The practice world cannot drift, so there is nothing to audit here.</p>
        </div>
        <Link href="/audit" className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline">
          See where recorded AI flights went wrong <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    );
  }
  const th = a.thresholds ?? THRESHOLDS;
  const last = a.latest;
  return (
    <div id="panel-world" role="tabpanel" aria-labelledby="tab-world" className="flex flex-col gap-5">
      <section className="grid grid-cols-3 gap-px overflow-hidden rounded-xl border border-line bg-line text-center">
        {[
          ["Trusted", `${Math.round(a.trusted_share * 100)}%`],
          ["Events", String(Object.values(a.counts).reduce((x, y) => x + y, 0))],
          ["Re-anchors", String(a.reanchors)],
        ].map(([k, v]) => (
          <div key={k} className="bg-surface px-2 py-2.5">
            <div className="text-[11px] text-muted">{k}</div>
            <div className="num text-lg font-semibold">{v}</div>
          </div>
        ))}
      </section>
      <div className="flex flex-col gap-4">
        <Trace title="Place matches your photo" help={`below ${th.scene_min} = drifted`} values={a.series.map((r) => r.scene)} min={0.5} />
        <Trace title="Drone matches itself" help={`below ${th.drone_min} = morphed`} values={a.series.map((r) => r.drone)} min={0.5} />
      </div>
      {last && (
        <p className={`text-sm font-medium ${last.trusted ? "text-clear" : "text-collision"}`}>
          {last.trusted ? "Trusted: this is still your place." : "Untrusted: the world has drifted from your photo."}
        </p>
      )}
      {a.events.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="eyebrow">Where it went wrong</h2>
          {a.events.slice().reverse().slice(0, 8).map((e, i) => (
            <article key={`${e.chunk}-${i}`} className="overflow-hidden rounded-xl border border-line bg-surface">
              {e.thumb && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={`data:image/jpeg;base64,${e.thumb}`} alt={e.detail} className="w-full" />
              )}
              <div className="p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wide text-collision">{AUDIT_KIND[e.kind].label}</span>
                  <span className="num text-[11px] text-muted">chunk {e.chunk}</span>
                </div>
                <p className="mt-1 text-sm">{e.detail}</p>
              </div>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}

/** The newest Pilot Lab result, with a way in. */
function LabCard() {
  const [run, setRun] = useState<LabRunSummary | null>(null);
  useEffect(() => {
    fetch("/engine/lab/runs")
      .then((r) => r.json())
      .then((rows: LabRunSummary[]) => setRun(rows.find((r) => r.best) ?? rows[0] ?? null))
      .catch(() => {});
  }, []);
  return (
    <section className="rounded-xl border border-line bg-surface p-4">
      <h2 className="flex items-center gap-2 font-semibold">
        <FlaskConical className="h-4 w-4 text-accent" aria-hidden /> Pilot Lab
      </h2>
      <p className="mt-1.5 text-sm leading-relaxed text-ink-2">
        Import a pilot&apos;s weights; it flies from pixels, learns from every crash and close call (imitation + reinforcement
        learning) and is re-scored on flights it never trained on.
      </p>
      {run?.before && run.after && (
        <p className="num mt-3 text-sm">
          Last run: crashes <span className="text-ink-2">{Math.round(run.before.crash_rate * 100)}%</span> →{" "}
          <b className="text-clear">{Math.round(run.after.crash_rate * 100)}%</b>, distance {run.before.mean_distance_m.toFixed(1)} →{" "}
          <b className="text-clear">{run.after.mean_distance_m.toFixed(1)} m</b>
        </p>
      )}
      <Link href="/lab" className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent-fill px-3 py-2 text-sm font-medium text-white hover:opacity-90">
        Open the Pilot Lab <ArrowRight className="h-4 w-4" />
      </Link>
    </section>
  );
}
