"use client";

import { useEffect, useMemo, useState } from "react";
import { CircleCheck, CircleX, Ghost } from "lucide-react";
import { ToolHeader } from "@/components/ToolNav";
import { SignalChart } from "@/components/audit/SignalChart";
import { AUDIT_KIND, THRESHOLDS, type Audit, type AuditSummary } from "@/lib/lab";
import type { Catalog } from "@/lib/model";

const CHUNKS_PER_S = 1.94; // LingBot World 2, measured
const secs = (k: number) => `${(k / CHUNKS_PER_S).toFixed(0)} s`;

export default function AuditPage() {
  const [list, setList] = useState<AuditSummary[] | null>(null);
  const [titles, setTitles] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [audit, setAudit] = useState<Audit | null>(null);
  const [chunk, setChunk] = useState<number | null>(null);

  useEffect(() => {
    fetch("/engine/audits").then((r) => r.json()).then((rows: AuditSummary[]) => {
      const lingbot = rows.filter((r) => r.world === "reactor");
      setList(lingbot);
      // Open on the flight that went most wrong: the clearest demonstration.
      setSelected((cur) => cur ?? [...lingbot].sort((a, b) => a.trusted_share - b.trusted_share)[0]?.run ?? null);
    }).catch(() => setList([]));
    fetch("/engine/catalog").then((r) => r.json()).then((c: Catalog) =>
      setTitles(Object.fromEntries(c.worlds.map((w) => [w.key, w.title])))).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selected) return;
    fetch(`/engine/audits/${selected}`).then((r) => r.json()).then((a: Audit) => {
      setAudit(a);
      setChunk(a.first_failure ?? 0);
    });
  }, [selected]);

  const points = useMemo(
    () => (audit?.readings ?? []).map((r) => ({ k: r.chunk, scene: r.scene, drone: r.drone_match, ok: r.trusted })),
    [audit],
  );
  const reading = audit?.readings.find((r) => r.chunk === chunk) ?? null;
  const th = audit?.thresholds ?? THRESHOLDS;
  const name = (scene: string) => titles[scene] ?? scene;

  return (
    <div className="sim min-h-screen bg-bg text-ink">
      <ToolHeader badge="World audit" />
      <main className="mx-auto max-w-7xl px-4 pb-24 pt-8">
        <p className="eyebrow">Where the world model went wrong</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">World audit</h1>
        <p className="mt-3 max-w-3xl text-ink-2">
          A generative world is asked to keep your place, your drone and only the obstacles you ask for. On long flights
          LingBot World 2 breaks all three. Every chunk is checked against the seed photo with a pretrained vision network,
          so each instance is caught, timed and kept. During live flights the same audit restarts the world from the last
          frame it trusted.
        </p>

        <section className="mt-8 grid gap-6 lg:grid-cols-[300px_1fr]">
          <aside className="space-y-2">
            <h2 className="text-sm font-semibold">Recorded LingBot flights</h2>
            {list === null && <p className="text-sm text-muted">Loading…</p>}
            {list?.length === 0 && <p className="text-sm text-muted">No recorded LingBot flights yet.</p>}
            <ul className="space-y-2">
              {list?.map((f) => {
                const n = Object.values(f.counts ?? {}).reduce((a, b) => a + b, 0);
                return (
                  <li key={f.run}>
                    <button onClick={() => setSelected(f.run)}
                      className={`w-full rounded-lg border p-3 text-left transition ${selected === f.run ? "border-accent bg-accent-soft" : "border-line bg-surface hover:border-line-strong"}`}>
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-medium">{name(f.scene)}</span>
                        <span className="num text-xs text-muted">{secs(f.chunks)}</span>
                      </div>
                      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-collision/40" aria-hidden>
                        <div className="h-full bg-clear" style={{ width: `${f.trusted_share * 100}%` }} />
                      </div>
                      <p className="num mt-1.5 text-[11px] text-ink-2">
                        {Math.round(f.trusted_share * 100)}% trusted · {n ? `${n} event${n > 1 ? "s" : ""}` : "no events"}
                        {f.first_failure != null ? ` · first at ${secs(f.first_failure)}` : ""}
                      </p>
                      <p className="num mt-0.5 text-[10px] text-muted">{f.run.replace("flight-", "")}</p>
                    </button>
                  </li>
                );
              })}
            </ul>
          </aside>

          <div className="min-w-0">
            {!audit ? (
              <div className="grid h-80 place-items-center rounded-xl border border-dashed border-line text-sm text-muted">Pick a flight</div>
            ) : (
              <div className="space-y-5">
                <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-4">
                  {[
                    ["Trusted", `${Math.round(audit.trusted_share * 100)}%`, "of chunks passed every check"],
                    ["First failure", audit.first_failure != null ? secs(audit.first_failure) : "none", audit.first_failure != null ? `chunk ${audit.first_failure}` : "the world held"],
                    ["Events", String(audit.events.length), Object.entries(audit.counts).map(([k, v]) => `${v} ${k}`).join(", ") || "—"],
                    ["Length", secs(audit.chunks), `${audit.chunks} chunks · ${name(audit.scene)}`],
                  ].map(([k, v, s]) => (
                    <div key={k} className="bg-surface px-4 py-3">
                      <div className="text-[11px] text-muted">{k}</div>
                      <div className="num mt-0.5 text-xl font-semibold">{v}</div>
                      <div className="truncate text-[11px] text-ink-2" title={s}>{s}</div>
                    </div>
                  ))}
                </div>

                <div className="rounded-xl border border-line bg-surface p-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h2 className="text-sm font-semibold">Similarity to the seed photo, every chunk</h2>
                    <p className="text-[11px] text-muted">Shaded: untrusted · markers: S drift, C cut, L colour, D drone, P pop-in · click to inspect</p>
                  </div>
                  <SignalChart points={points} events={audit.events} anchors={audit.anchors} sceneMin={th.scene_min} droneMin={th.drone_min}
                    selected={chunk} onSelect={setChunk} />
                </div>

                {chunk != null && (
                  <div className="grid gap-4 rounded-xl border border-line bg-surface p-4 md:grid-cols-[1fr_260px]">
                    <div>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={`/engine/audits/${audit.run}/frame/${chunk}.jpg`} alt={`What LingBot rendered at chunk ${chunk}`}
                        className="aspect-video w-full rounded-lg bg-black object-cover" />
                      <input type="range" min={0} max={audit.chunks - 1} value={chunk} onChange={(e) => setChunk(Number(e.target.value))}
                        className="mt-3 h-1.5 w-full accent-[var(--accent)]" aria-label="Chunk" />
                    </div>
                    <div className="text-sm">
                      <div className="num text-xs text-muted">chunk {chunk} · {secs(chunk)}</div>
                      {reading && (
                        <>
                          <div className={`mt-2 inline-flex items-center gap-1.5 text-sm font-semibold ${reading.trusted ? "text-clear" : "text-collision"}`}>
                            {reading.trusted ? <CircleCheck className="h-4 w-4" /> : <CircleX className="h-4 w-4" />}
                            {reading.trusted ? "Trusted" : "Untrusted"}
                          </div>
                          <dl className="num mt-3 space-y-2">
                            {[
                              ["Place matches photo", reading.scene, th.scene_min, true],
                              ["Drone matches itself", reading.drone_match, th.drone_min, true],
                              ["Colour drift (ΔE)", reading.colour, th.colour_max, false],
                              ["Same as last chunk", reading.continuity ?? 1, th.cut_min, true],
                            ].map(([k, v, lim, up]) => {
                              const ok = up ? (v as number) >= (lim as number) : (v as number) <= (lim as number);
                              return (
                                <div key={k as string} className="flex items-baseline justify-between gap-2">
                                  <dt className="text-ink-2">{k as string}</dt>
                                  <dd className={ok ? "" : "font-semibold text-collision"}>
                                    {up ? `${Math.round((v as number) * 100)}%` : (v as number).toFixed(0)}
                                    <span className="text-[10px] font-normal text-muted"> {up ? "≥" : "≤"} {up ? `${Math.round((lim as number) * 100)}%` : (lim as number)}</span>
                                  </dd>
                                </div>
                              );
                            })}
                          </dl>
                          {reading.events.length > 0 && (
                            <ul className="mt-3 space-y-1">
                              {reading.events.map((e, i) => (
                                <li key={i} className="text-xs text-collision">{AUDIT_KIND[e.kind].label}: {e.detail}</li>
                              ))}
                            </ul>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                )}

                <div>
                  <h2 className="text-sm font-semibold">Every instance, with the frame</h2>
                  {audit.events.length === 0 ? (
                    <p className="mt-2 text-sm text-muted">Nothing went wrong on this flight: the world held for {secs(audit.chunks)}.</p>
                  ) : (
                    <ul className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                      {audit.events.map((e, i) => (
                        <li key={i}>
                          <button onClick={() => setChunk(e.chunk)} className="w-full overflow-hidden rounded-xl border border-line bg-surface text-left hover:border-line-strong">
                            {e.thumb && (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img src={`data:image/jpeg;base64,${e.thumb}`} alt={`${e.kind} at chunk ${e.chunk}`} className="aspect-video w-full bg-black object-cover" />
                            )}
                            <div className="p-3">
                              <div className="flex items-center justify-between gap-2">
                                <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-collision">
                                  <Ghost className="h-3.5 w-3.5" aria-hidden /> {AUDIT_KIND[e.kind].label}
                                </span>
                                <span className="num text-xs text-muted">{secs(e.chunk)} · chunk {e.chunk}</span>
                              </div>
                              <p className="mt-1 text-sm">{e.detail}</p>
                              <p className="mt-0.5 text-[11px] text-muted">{AUDIT_KIND[e.kind].help}</p>
                            </div>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            )}
          </div>
        </section>

        <section className="mt-16 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {[
            ["Place matches the photo", `A ResNet-18 trained on ImageNet turns each frame (drone masked out) into a 512-number description; it is compared with the seed photo's. Places that were kept stayed at 0.86–0.92 over 140 chunks; places that turned into another room fell to 0.67–0.79. Limit: ${THRESHOLDS.scene_min}.`],
            ["Drone matches itself", `The same network compares crops around the drone, at five sizes, with the seed's drone. Healthy drones: 0.80–0.95. Ballooned, stretched or re-rendered: 0.71–0.76. Limit: ${THRESHOLDS.drone_min}.`],
            ["Colour drift", `Mean CIELAB colour of the background vs the seed. Kept places wandered up to ΔE 14 as the light changed; a scene that turned blue reached 33. Limit: ${THRESHOLDS.colour_max}.`],
            ["Scene cut", `Similarity between consecutive chunks. Real motion stays above 0.85; a jump to another place falls below ${THRESHOLDS.cut_min}.`],
            ["Pop-in", "A person or vehicle, big enough to matter, that appears mid-frame (not entering from an edge), was absent from the three chunks before and is still there in the next: an obstacle nobody asked for. Requested events are excused."],
            ["What happens live", "Two failing chunks make an event; four in a row restart LingBot from the last frame that passed every check (same session, same prompt, ~9 s), at most every 16 chunks."],
          ].map(([h, t]) => (
            <div key={h} className="rounded-xl border border-line bg-surface p-4">
              <h3 className="text-sm font-semibold">{h}</h3>
              <p className="mt-1.5 text-sm text-ink-2">{t}</p>
            </div>
          ))}
        </section>
      </main>
    </div>
  );
}
