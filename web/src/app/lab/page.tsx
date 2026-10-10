"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Cpu, FlaskConical, Loader2, Square, Upload } from "lucide-react";
import { ToolHeader } from "@/components/ToolNav";
import { Curve } from "@/components/lab/Curve";
import { Mistakes } from "@/components/lab/Mistakes";
import { Replay } from "@/components/lab/Replay";
import { describeScenario, type LabRun, type LabRunSummary, type PilotInfo } from "@/lib/lab";

const pct = (v: number) => `${Math.round(v * 100)}%`;
const pts = (v: number) => `${Math.round(v * 100)} pts`;

export default function LabPage() {
  const [pilots, setPilots] = useState<PilotInfo[]>([]);
  const [runs, setRuns] = useState<LabRunSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [run, setRun] = useState<LabRun | null>(null);
  const [base, setBase] = useState("factory-pilot.pt");
  const [iterations, setIterations] = useState(10);
  const [episodes, setEpisodes] = useState(48);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const [scenario, setScenario] = useState<string | null>(null);
  const replayRef = useRef<HTMLElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadLists = useCallback(async () => {
    const [p, r] = await Promise.all([
      fetch("/engine/lab/pilots").then((x) => x.json()).catch(() => []),
      fetch("/engine/lab/runs").then((x) => x.json()).catch(() => []),
    ]);
    setPilots(p);
    setRuns(r);
    const finished = r.filter((x: LabRunSummary) => x.best && x.after);
    const strongest = finished.sort((a: LabRunSummary, b: LabRunSummary) => a.after!.crash_rate - b.after!.crash_rate)[0];
    setSelected((cur) => cur ?? (r.find((x: LabRunSummary) => x.status === "running") ?? strongest ?? r[0])?.id ?? null);
  }, []);

  useEffect(() => {
    Promise.resolve().then(loadLists);
  }, [loadLists]);

  // The selected run; polled while it is still learning.
  useEffect(() => {
    if (!selected) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      const r: LabRun | null = await fetch(`/engine/lab/runs/${selected}`).then((x) => (x.ok ? x.json() : null)).catch(() => null);
      if (stop) return;
      setRun(r);
      if (r?.status === "running") timer = setTimeout(tick, 2000);
      else loadLists();
    };
    tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [selected, loadLists]);

  const running = runs.find((r) => r.status === "running");

  async function start() {
    setError(null);
    const res = await fetch("/engine/lab/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ base, iterations, episodes }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) return setError(body.detail ?? "Could not start the run");
    setRun(null);
    setSelected(body.run);
    setScenario(null);
    loadLists();
  }

  async function stopRun() {
    await fetch("/engine/lab/stop", { method: "POST" });
  }

  async function upload(file: File) {
    setUploading(true);
    setError(null);
    const b64 = await new Promise<string>((ok, fail) => {
      const r = new FileReader();
      r.onload = () => ok(String(r.result));
      r.onerror = () => fail(r.error);
      r.readAsDataURL(file);
    });
    const res = await fetch("/engine/lab/pilots", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: file.name, data_b64: b64 }),
    });
    const body = await res.json().catch(() => ({}));
    setUploading(false);
    if (!res.ok) return setError(body.detail ?? "Upload failed");
    setBase(body.file);
    loadLists();
  }

  const rows = run?.rows ?? [];
  const labels = rows.map((r) => r.version);
  const bestIdx = run?.final ? rows.findIndex((r) => r.version === run.final!.best) : -1;
  const before = rows[0];
  const after = bestIdx >= 0 ? rows[bestIdx] : rows[rows.length - 1];
  const fixed = run?.final?.fixed ?? [];

  const replays = useMemo(() => {
    if (!run?.final) return [];
    const scen = new Map((run.episodes_before ?? []).map((e) => [e.scenario.id, e]));
    const aft = new Map((run.episodes_after ?? []).map((e) => [e.scenario.id, e]));
    return run.final.replays.map((id) => ({ id, before: scen.get(id), after: aft.get(id) }));
  }, [run]);
  const activeScenario = scenario && replays.some((r) => r.id === scenario) ? scenario : replays[0]?.id;
  const rep = replays.find((r) => r.id === activeScenario);

  return (
    <div className="sim min-h-screen bg-bg text-ink">
      <ToolHeader badge="Pilot Lab" />
      <main className="mx-auto max-w-7xl px-4 pb-24 pt-8">
        {/* ------------------------------------------------------------ headline */}
        <section className="grid gap-8 lg:grid-cols-[1fr_auto] lg:items-end">
          <div>
            <p className="eyebrow">Recursive learning from mistakes</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Pilot Lab</h1>
            <p className="mt-3 max-w-2xl text-ink-2">
              Import a pilot&apos;s weights. It flies from camera pixels alone, every crash and close call it makes becomes
              training data, and its weights are updated by imitation and reinforcement learning. Each version is scored on
              flights it never trains on, so the before and after below is a fair comparison.
            </p>
          </div>
          {before && after && after !== before && fixed.length > 0 && (
            <dl className="grid grid-cols-3 gap-px overflow-hidden rounded-xl border border-line bg-line text-center">
              {[
                { k: "Crash rate", a: pct(before.crash_rate), b: pct(after.crash_rate) },
                { k: "Distance flown", a: `${before.mean_distance_m.toFixed(1)} m`, b: `${after.mean_distance_m.toFixed(1)} m` },
                { k: "Mistakes fixed", a: `${fixed.length || "—"}`, b: fixed.length ? `${fixed.filter((m) => m.fixed).length}` : "—" },
              ].map((s) => (
                <div key={s.k} className="bg-surface px-5 py-3">
                  <dt className="text-[11px] text-muted">{s.k}</dt>
                  <dd className="num mt-1 flex items-center justify-center gap-1.5 text-lg font-semibold">
                    <span className="text-ink-2">{s.a}</span>
                    <ArrowRight className="h-4 w-4 text-muted" aria-label="to" />
                    <span className="text-clear">{s.b}</span>
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </section>

        <section className="mt-8 grid gap-6 lg:grid-cols-[340px_1fr]">
          {/* ------------------------------------------------------------ setup */}
          <aside className="space-y-4">
            <div className="rounded-xl border border-line bg-surface p-4">
              <h2 className="text-sm font-semibold">1 · Pilot to improve</h2>
              <ul className="mt-3 space-y-2" role="radiogroup" aria-label="Pilot">
                {pilots.map((p) => (
                  <li key={p.file}>
                    <button
                      role="radio"
                      aria-checked={base === p.file}
                      disabled={!!running}
                      onClick={() => setBase(p.file)}
                      className={`w-full rounded-lg border p-3 text-left transition disabled:cursor-not-allowed ${
                        base === p.file ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium">{p.name}</span>
                        <span className="text-[10px] uppercase tracking-wide text-muted">{p.source}</span>
                      </div>
                      {p.trained_on && <p className="mt-0.5 text-xs text-ink-2">Trained on {p.trained_on}</p>}
                      {p.scores?.field && (
                        <p className="num mt-1 text-xs text-muted">
                          Crashes {pct(p.scores["open field"]?.crash_rate ?? 0)} where it trained,{" "}
                          <span className="text-warning">{pct(p.scores.field.crash_rate)}</span> in the field
                        </p>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
              <input
                ref={fileRef}
                type="file"
                accept=".pt"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
              />
              <button
                onClick={() => fileRef.current?.click()}
                disabled={uploading || !!running}
                className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-line-strong px-3 py-2 text-sm text-ink-2 hover:text-ink disabled:opacity-50"
              >
                {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                Import weights (.pt)
              </button>
            </div>

            <div className="rounded-xl border border-line bg-surface p-4">
              <h2 className="text-sm font-semibold">2 · Improvement loop</h2>
              <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                <label className="block">
                  <span className="text-xs text-muted">Iterations</span>
                  <input type="number" min={1} max={30} value={iterations} disabled={!!running}
                    onChange={(e) => setIterations(Number(e.target.value))}
                    className="num mt-1 w-full rounded-lg border border-line bg-surface-2 px-2.5 py-1.5" />
                </label>
                <label className="block">
                  <span className="text-xs text-muted">Flights per iteration</span>
                  <select value={episodes} disabled={!!running} onChange={(e) => setEpisodes(Number(e.target.value))}
                    className="num mt-1 w-full rounded-lg border border-line bg-surface-2 px-2 py-1.5">
                    {[24, 48, 64, 96].map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                </label>
              </div>
              {running ? (
                <button onClick={stopRun} className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg border border-line-strong px-3 py-2 text-sm font-medium hover:bg-surface-2">
                  <Square className="h-4 w-4" /> Finish early
                </button>
              ) : (
                <button onClick={start} className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent-fill px-3 py-2 text-sm font-semibold text-accent-ink hover:brightness-110">
                  <FlaskConical className="h-4 w-4" /> Run the loop
                </button>
              )}
              <p className="mt-2 flex items-center gap-1.5 text-[11px] text-muted">
                <Cpu className="h-3.5 w-3.5" aria-hidden /> Free: runs on this machine (~1 min per iteration), no Reactor credit.
              </p>
              {error && <p className="mt-2 text-xs text-collision" role="alert">{error}</p>}
            </div>

            {runs.length > 0 && (
              <div className="rounded-xl border border-line bg-surface p-4">
                <h2 className="text-sm font-semibold">Runs</h2>
                <ul className="mt-2 divide-y divide-line">
                  {runs.map((r) => (
                    <li key={r.id}>
                      <button onClick={() => { setSelected(r.id); setScenario(null); }}
                        className={`flex w-full items-center justify-between gap-2 py-2 text-left text-sm ${selected === r.id ? "text-ink" : "text-ink-2 hover:text-ink"}`}>
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{r.base_name ?? r.base}</span>
                          <span className="num block text-[11px] text-muted">{r.id.replace("lab-", "")} · {r.versions} versions</span>
                        </span>
                        {r.status === "running" ? (
                          <span className="inline-flex items-center gap-1 text-xs text-accent"><Loader2 className="h-3.5 w-3.5 animate-spin" /> learning</span>
                        ) : r.before && r.after ? (
                          <span className="num text-xs">{pct(r.before.crash_rate)} → <b className="text-clear">{pct(r.after.crash_rate)}</b></span>
                        ) : (
                          <span className="text-xs text-muted">{r.status}</span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </aside>

          {/* ------------------------------------------------------------ curves */}
          <div className="min-w-0 space-y-4">
            {run?.status === "running" && (
              <div className="rounded-xl border border-accent/40 bg-accent-soft p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    <Loader2 className="h-4 w-4 animate-spin text-accent" /> {run.progress.stage}
                  </p>
                  <span className="num text-xs text-ink-2">iteration {run.progress.iteration ?? 0} / {run.progress.iterations}</span>
                </div>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-2">
                  <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${(100 * (run.progress.iteration ?? 0)) / (run.progress.iterations || 1)}%` }} />
                </div>
              </div>
            )}
            {rows.length === 0 ? (
              <div className="grid h-64 place-items-center rounded-xl border border-dashed border-line text-sm text-muted">
                {selected ? "Scoring the imported pilot…" : "No runs yet: pick a pilot and run the loop."}
              </div>
            ) : (
              <>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Curve title="Crash rate" help="Share of held-out flights that end in a collision" values={rows.map((r) => r.crash_rate)} labels={labels}
                    hover={hover} onHover={setHover} best={bestIdx} format={pct} formatDelta={pts} min={0} max={1} better="down"
                    band={rows.map((r) => r.beta ?? 0)} />
                  <Curve title="Distance flown" help="Metres covered before the 10 s limit or a crash" values={rows.map((r) => r.mean_distance_m)} labels={labels}
                    hover={hover} onHover={setHover} best={bestIdx} format={(v) => `${v.toFixed(1)} m`} better="up" />
                  <Curve title="Close calls per flight" help="Decisions taken with less than 0.6 m of clearance" values={rows.map((r) => r.near_miss_steps)} labels={labels}
                    hover={hover} onHover={setHover} best={bestIdx} format={(v) => v.toFixed(1)} min={0} better="down" />
                  <Curve title="Agrees with the expert" help="Decisions matching the privileged planner's" values={rows.map((r) => r.expert_agreement)} labels={labels}
                    hover={hover} onHover={setHover} best={bestIdx} format={pct} formatDelta={pts} min={0} max={1} better="up" />
                </div>
                <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
                  <span className="inline-flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-full bg-clear" /> best version (kept)</span>
                  <span className="inline-flex items-center gap-1.5"><span className="inline-block h-2.5 w-1.5 rounded-sm bg-anomaly opacity-60" /> expert co-pilot share while training (DAgger β), handed over to the pilot as it improves</span>
                </p>
                <details className="rounded-xl border border-line bg-surface">
                  <summary className="cursor-pointer px-4 py-3 text-sm font-medium">Training log: every version, its data and its losses</summary>
                  <div className="overflow-x-auto px-4 pb-4">
                    <table className="num w-full min-w-[720px] text-left text-xs">
                      <thead className="text-muted">
                        <tr className="border-b border-line">
                          {["Version", "Crash", "Distance", "Close calls", "Agreement", "Expert share", "New states", "Dataset", "Flights w/ mistakes", "Imitation loss", "RL loss", "Value loss"].map((h) => (
                            <th key={h} className="py-2 pr-3 font-normal">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r, i) => (
                          <tr key={r.version} className={`border-b border-line ${i === bestIdx ? "text-clear" : ""}`}>
                            <td className="py-1.5 pr-3 font-medium">{r.version}</td>
                            <td className="pr-3">{pct(r.crash_rate)}</td>
                            <td className="pr-3">{r.mean_distance_m.toFixed(1)} m</td>
                            <td className="pr-3">{r.near_miss_steps.toFixed(1)}</td>
                            <td className="pr-3">{pct(r.expert_agreement)}</td>
                            <td className="pr-3">{r.beta != null ? pct(r.beta) : "—"}</td>
                            <td className="pr-3">{r.states ?? "—"}</td>
                            <td className="pr-3">{r.dataset ?? "—"}</td>
                            <td className="pr-3">{r.mistakes ?? "—"}</td>
                            <td className="pr-3">{r.loss_imitation ?? "—"}</td>
                            <td className="pr-3">{r.loss_rl ?? "—"}</td>
                            <td className="pr-3">{r.loss_value ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              </>
            )}
          </div>
        </section>

        {/* ------------------------------------------------------------ before / after */}
        {run?.final && rep && (
          <section ref={replayRef} className="mt-12 scroll-mt-20">
            <p className="eyebrow">Before and after</p>
            <h2 className="mt-1 text-2xl font-semibold tracking-tight">Same flight, same obstacles, two pilots</h2>
            <p className="mt-1 text-ink-2">Held-out flights the imported pilot crashed on, replayed with {run.final.best}.</p>
            <div role="tablist" aria-label="Flight" className="mt-4 flex flex-wrap gap-2">
              {replays.map((r) => (
                <button key={r.id} role="tab" aria-selected={r.id === activeScenario} onClick={() => setScenario(r.id)}
                  className={`rounded-lg border px-3 py-1.5 text-left text-xs transition ${r.id === activeScenario ? "border-accent bg-accent-soft text-ink" : "border-line text-muted hover:text-ink"}`}>
                  {r.before ? describeScenario(r.before.scenario) : r.id}
                </button>
              ))}
            </div>
            <div className="mt-4 rounded-xl border border-line bg-surface p-4">
              <Replay
                key={`${run.id}-${rep.id}`}
                runId={run.id}
                scenario={rep.id}
                maxSteps={run.max_steps}
                before={{
                  version: "v0",
                  title: `Before · v0 (${run.base_meta?.name ?? run.base})`,
                  frames: run.frames.v0?.[rep.id] ?? 0,
                  trace: run.final.replay_traces?.v0?.[rep.id]?.trace,
                  crashed: run.final.replay_traces?.v0?.[rep.id]?.crashed ?? rep.before?.crashed ?? false,
                  distance: run.final.replay_traces?.v0?.[rep.id]?.distance ?? rep.before?.distance,
                }}
                after={{
                  version: run.final.best,
                  title: `After · ${run.final.best}`,
                  frames: run.frames[run.final.best]?.[rep.id] ?? 0,
                  trace: run.final.replay_traces?.[run.final.best]?.[rep.id]?.trace,
                  crashed: run.final.replay_traces?.[run.final.best]?.[rep.id]?.crashed ?? rep.after?.crashed ?? false,
                  distance: run.final.replay_traces?.[run.final.best]?.[rep.id]?.distance ?? rep.after?.distance,
                }}
              />
            </div>
          </section>
        )}

        {/* ------------------------------------------------------------ mistakes */}
        {run?.final && fixed.length > 0 && (
          <section className="mt-12">
            <p className="eyebrow">Every mistake, tracked</p>
            <h2 className="mt-1 text-2xl font-semibold tracking-tight">What the imported pilot got wrong, and whether it still does</h2>
            <div className="mt-4">
              <Mistakes
                items={fixed}
                bestLabel={run.final.best}
                replayable={run.final.replays}
                onReplay={(id) => {
                  setScenario(id);
                  replayRef.current?.scrollIntoView({ behavior: "smooth" });
                }}
              />
            </div>
          </section>
        )}

        {/* ------------------------------------------------------------ method */}
        <section className="mt-16 grid gap-8 lg:grid-cols-[1fr_1fr]">
          <div>
            <p className="eyebrow">How one iteration works</p>
            <ol className="mt-3 space-y-3">
              {[
                ["Fly", "48 fresh training flights in parallel (12 CPU cores), the pilot at the controls with a little exploration. Early on a privileged expert takes some decisions (DAgger β) so a weak pilot still reaches the hard parts."],
                ["Find the mistakes", "Every crash and every close call (< 0.6 m), plus the six decisions that led into it."],
                ["Relabel", "A planner that sees the true obstacle positions simulates each candidate command 1.5 s ahead on the quadrotor's dynamics and names the safe one. Steps before a mistake count 3×."],
                ["Reinforce", "Imitation on everything gathered so far, plus advantage-weighted regression: decisions that beat the value head's expectation are strengthened, a value head learns the return."],
                ["Re-score", "On 32 held-out flights it never trains on. The best version is kept and saved as weights you can fly."],
              ].map(([h, t], i) => (
                <li key={h} className="flex gap-3">
                  <span className="num mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-surface-2 text-xs font-semibold">{i + 1}</span>
                  <p className="text-sm text-ink-2"><b className="text-ink">{h}.</b> {t}</p>
                </li>
              ))}
            </ol>
          </div>
          <div className="rounded-xl border border-line bg-surface p-5 text-sm text-ink-2">
            <h3 className="font-semibold text-ink">What is being trained</h3>
            <p className="mt-2">
              A convolutional policy (0.49 M weights): the chase-camera view in colour plus the change since the last decision,
              mapped to one of 11 drone commands, with a value head. Contrast-normalised input, so day and night read alike.
            </p>
            <h3 className="mt-4 font-semibold text-ink">Where it trains, honestly</h3>
            <p className="mt-2">
              In the practice world, where obstacles have true positions and the drone has quadrotor physics: crashes are facts,
              not guesses. Thousands of flights per run would cost hundreds of dollars on a generative world model, so the
              learned pilot is then flown there (and in your own photos) to see if it transfers.
            </p>
            <h3 className="mt-4 font-semibold text-ink">The imported pilot</h3>
            <p className="mt-2">
              The factory pilot only ever saw sunny, sparse, static open fields. Put in warehouse aisles, at night, with someone
              stepping into its path, it crashes about two flights in three. Bring your own weights with the same input and
              outputs to test them the same way.
            </p>
          </div>
        </section>
      </main>
    </div>
  );
}
