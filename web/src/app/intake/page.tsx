"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Check, FileVideo, Loader2, Scissors, Send, Sparkles, Upload, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { AppHeader } from "@/components/Brand";
import { Count, Item, Ring, Stagger } from "@/components/Motion";
import { ENGINE_URL, band, delJSON, fmt, getJSON, postJSON, type ClipRow, type Workflow } from "@/lib/solosim";

type Row = ClipRow & { workflow: Workflow };

/** The cut the gate proposes, the evidence behind it, and the handles to disagree with it. */
function TrimCard({ r, onSaved, onError }: { r: Row; onSaved: () => void; onError: (m: string) => void }) {
  const tr = r.intake;
  const [start, setStart] = useState(tr?.start ?? 0);
  const [end, setEnd] = useState(tr?.end ?? r.duration);
  const [saving, setSaving] = useState(false);
  if (!tr) return null;
  const dirty = Math.abs(start - (tr.start ?? 0)) > 0.05 || Math.abs(end - (tr.end ?? r.duration)) > 0.05;
  const conf = band(tr.confidence);

  async function save() {
    setSaving(true);
    try {
      await postJSON(`/clips/${r.id}/trim`, { start, end });
      onSaved();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-3 rounded-xl border border-line bg-surface-2/60 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-sm font-semibold"><Scissors className="h-4 w-4 text-accent" /> The useful part</span>
        <span className={`pill ${conf.cls}`}>{Math.round(tr.confidence * 100)}% sure · {conf.label}</span>
        {tr.applied ? <span className="pill bg-clear/15 text-clear">cut</span> : <span className="pill bg-surface-2 text-muted">proposed</span>}
        {tr.by === "qc" && <span className="pill bg-surface-2 text-muted">your cut</span>}
        {tr.topic && <span className="pill bg-accent-soft text-accent">narrowed to &ldquo;{tr.topic}&rdquo;</span>}
      </div>

      {/* The original timeline with the kept region lit up. */}
      <div className="num mt-2.5 text-[11px] text-muted">
        kept <b className="text-ink">{fmt(tr.kept)}</b> of {fmt(tr.duration)} · dropped {Math.round(tr.cut_share * 100)}%
      </div>
      <div className="relative mt-1.5 h-3 overflow-hidden rounded-full bg-surface-2">
        <div className="absolute inset-y-0 bg-accent/80"
          style={{ left: `${(100 * tr.start) / Math.max(0.1, tr.duration)}%`, width: `${(100 * tr.kept) / Math.max(0.1, tr.duration)}%` }} />
      </div>

      <ul className="mt-2.5 space-y-1 text-xs text-ink-2">
        {tr.reasons.map((why) => (
          <li key={why} className="flex gap-1.5"><span className="text-accent">·</span>{why}</li>
        ))}
      </ul>

      {!tr.auto && (
        <p className="mt-2 rounded-lg border border-caution/40 bg-caution/10 px-2.5 py-1.5 text-xs">
          The gate did not cut this on its own. Set the range yourself, or leave the whole clip.
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-end gap-3">
        {([["Start", start, setStart], ["End", end, setEnd]] as const).map(([label, v, set]) => (
          <label key={label} className="text-[11px] text-muted">
            {label} (s)
            <input type="number" step="0.1" min={0} max={tr.duration} value={Number(v).toFixed(1)}
              onChange={(e) => set(Math.max(0, Math.min(tr.duration, Number(e.target.value))))}
              className="num mt-0.5 block w-24 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink" />
          </label>
        ))}
        <button onClick={save} disabled={!dirty || saving || end - start < 1} className="btn btn-quiet">
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scissors className="h-4 w-4" />} Use my cut
        </button>
      </div>
    </div>
  );
}

/** What the AI is claiming, and how much of it a person should expect to change. */
function DraftCard({ r }: { r: Row }) {
  const d = r.intake?.draft;
  if (!d?.drafted) return null;
  const mean = d.mean_confidence ?? 0;
  return (
    <div className="mt-3 rounded-xl border border-line bg-surface-2/60 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-sm font-semibold"><Sparkles className="h-4 w-4 text-accent" /> What the AI annotated</span>
        <span className={`pill ${band(mean).cls}`}>mean {Math.round(mean * 100)}% confident</span>
      </div>
      <div className="mt-2.5 grid grid-cols-3 gap-2 text-center">
        {([["likely right", d.high ?? 0, "text-clear"], ["worth a look", d.medium ?? 0, "text-warning"], ["unsure", d.low ?? 0, "text-collision"]] as const).map(
          ([label, n, cls]) => (
            <div key={label} className="rounded-lg bg-surface px-2 py-2">
              <p className={`num text-xl font-semibold ${cls}`}><Count to={n} duration={0.6} /></p>
              <p className="text-[11px] text-muted">{label}</p>
            </div>
          ),
        )}
      </div>
      <p className="mt-2 text-xs text-ink-2">
        <b className="text-ink">{d.drafted}</b> claims written from the pixels alone — no metadata, no filenames, no timestamps. The annotator
        verifies these instead of starting from an empty timeline.
      </p>
    </div>
  );
}

export default function IntakePage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [operator, setOperator] = useState("");
  const [title, setTitle] = useState("");
  const [topic, setTopic] = useState("");
  const [annotator, setAnnotator] = useState("");
  const [picked, setPicked] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const videoRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    try { const n = localStorage.getItem("solosim_operator"); if (n) setOperator(n); } catch {}
  }, []);

  const load = useCallback(() => getJSON<Row[]>("/clips").then(setRows).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!rows?.some((r) => r.job?.status === "running")) return;
    const t = setTimeout(load, 1200);
    return () => clearTimeout(t);
  }, [rows, load]);

  async function handoff(id: string) {
    try { localStorage.setItem("solosim_operator", operator); } catch {}
    try {
      await postJSON(`/clips/${id}/workflow`, { action: "handoff", annotator, note: "cut and first-pass annotations accepted by QC" });
      load();
    } catch (e) { setError((e as Error).message); }
  }

  async function remove(id: string, name: string) {
    if (!confirm(`Delete "${name}" and everything measured about it?`)) return;
    setRows((rs) => rs?.filter((r) => r.id !== id) ?? rs);
    try { await delJSON(`/clips/${id}`); } catch (e) { setError((e as Error).message); }
    load();
  }

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    const v = picked ?? videoRef.current?.files?.[0];
    if (!v) return setError("Pick a raw first-person clip.");
    try { localStorage.setItem("solosim_operator", operator); } catch {}
    setUploading(true); setError(null);
    const fd = new FormData();
    fd.append("video", v);
    fd.append("title", title || v.name.replace(/\.[^.]+$/, ""));
    fd.append("operator", operator);
    fd.append("topic", topic.trim());
    try {
      // Straight to the engine: the Next proxy truncates request bodies over 10MB.
      const r = await fetch(`${ENGINE_URL}/clips/intake`, { method: "POST", body: fd });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail ?? "Upload failed");
      setTitle("");
      setTopic("");
      setPicked(null);
      if (videoRef.current) videoRef.current.value = "";
      load();
    } catch (err) { setError((err as Error).message); } finally { setUploading(false); }
  }

  const queue = rows?.filter((r) => (r.workflow?.status ?? "draft") === "intake" || r.job?.status === "running") ?? null;

  return (
    <div className="sim min-h-screen bg-bg text-ink">
      <AppHeader />
      <main className="mx-auto max-w-[1600px] px-4 pb-24 pt-8 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <p className="eyebrow">QC intake</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Raw footage in, verifiable draft out</h1>
            <p className="mt-2 max-w-2xl text-ink-2">
              Raw clips land here first, before any paid annotator sees them. The gate finds where the work actually starts and stops — the
              wearer putting the camera on, walking to the bench, walking away — cuts the dead footage, then writes a first pass of
              annotations with a confidence on every claim. You check the cut, then hand it on. Nothing here reads a filename or a
              timestamp: every decision comes out of the pixels.
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted">Your name</span>
            <input value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="e.g. Priya"
              className="w-44 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-ink shadow-[var(--shadow-1)]" />
          </label>
        </div>

        <AnimatePresence>
          {error && (
            <motion.p initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className="mt-4 flex items-center justify-between gap-3 rounded-lg border border-collision/30 bg-collision/10 px-3 py-2 text-sm" role="alert">
              {error}
              <button onClick={() => setError(null)} className="text-muted hover:text-ink"><X className="h-4 w-4" /></button>
            </motion.p>
          )}
        </AnimatePresence>

        <div className="mt-8 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(320px,380px)]">
          <Stagger className="space-y-3">
            {queue === null && <li className="list-none text-muted">Loading…</li>}
            {queue?.length === 0 && (
              <Item className="card grid place-items-center gap-1 p-10 text-center">
                <FileVideo className="h-7 w-7 text-muted" />
                <p className="mt-1 font-medium">Nothing waiting</p>
                <p className="text-sm text-muted">Drop a raw clip on the right. Everything up to a verifiable draft runs on its own.</p>
              </Item>
            )}
            {queue?.map((r) => {
              const running = r.job?.status === "running";
              return (
                <Item key={r.id}>
                  <div className="card p-3">
                    <div className="grid grid-cols-[132px_1fr] gap-4 sm:grid-cols-[200px_1fr]">
                      <Link href={`/review/${r.id}?role=annotator`} className="stage relative block h-fit overflow-hidden rounded-xl"
                        style={{ aspectRatio: `${r.width} / ${r.height}` }}>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={`/engine/clips/${r.id}/frame.jpg?t=${(r.duration / 3).toFixed(1)}&w=400`} alt="" className="h-full w-full object-cover" loading="lazy" />
                        <span className="num absolute bottom-1 right-1 rounded bg-black/70 px-1.5 text-[10px] text-white">{fmt(r.duration)}</span>
                      </Link>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-baseline gap-2">
                          <Link href={`/review/${r.id}?role=annotator`} className="truncate font-semibold hover:underline">{r.title}</Link>
                          <span className="text-xs text-muted">{r.segments} segments · {fmt(r.duration)}</span>
                        </div>
                        {running ? (
                          <div className="mt-2 flex items-center gap-3">
                            <Ring value={r.job?.fraction ?? 0} />
                            <div className="min-w-0 flex-1">
                              <p className="truncate text-sm font-medium">{r.job?.stage}</p>
                              <div className="relative mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-2 sweep">
                                <div className="h-full rounded-full bg-accent transition-all duration-500" style={{ width: `${(r.job?.fraction ?? 0) * 100}%` }} />
                              </div>
                              <p className="mt-1.5 text-[11px] text-muted">Trim, then measurement, then the first pass of annotations — all automatic.</p>
                            </div>
                          </div>
                        ) : r.job?.status === "error" ? (
                          <p className="mt-2 text-sm text-collision">{r.job.stage}</p>
                        ) : (
                          <>
                            <TrimCard r={r} onSaved={load} onError={setError} />
                            <DraftCard r={r} />
                            <div className="mt-3 flex flex-wrap items-end gap-2">
                              <label className="text-[11px] text-muted">
                                Hand to
                                <input value={annotator} onChange={(e) => setAnnotator(e.target.value)} placeholder="annotator (optional)"
                                  className="mt-0.5 block w-44 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink" />
                              </label>
                              <button onClick={() => handoff(r.id)} className="btn btn-primary">
                                <Send className="h-4 w-4" /> Send to the annotator
                              </button>
                              <Link href={`/review/${r.id}?role=annotator`} className="btn btn-quiet">
                                Watch it <ArrowRight className="h-4 w-4" />
                              </Link>
                              <button onClick={() => remove(r.id, r.title)} className="btn btn-quiet ml-auto text-muted hover:text-collision">
                                Reject
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                </Item>
              );
            })}

            {/* Everything already handed on, so QC can see the queue draining. */}
            {rows && rows.length > (queue?.length ?? 0) && (
              <Item className="card p-3">
                <p className="text-sm font-semibold">Already with the annotators</p>
                <ul className="mt-2 space-y-1.5 text-sm">
                  {rows.filter((r) => (r.workflow?.status ?? "draft") !== "intake" && r.job?.status !== "running").map((r) => (
                    <li key={r.id} className="flex items-center gap-2">
                      <Check className="h-3.5 w-3.5 shrink-0 text-clear" />
                      <Link href={`/review/${r.id}?role=annotator`} className="truncate hover:underline">{r.title}</Link>
                      <span className="num ml-auto shrink-0 text-xs text-muted">
                        {r.intake?.draft?.drafted ? `${r.intake.draft.drafted} AI claims` : `${r.segments} segments`}
                      </span>
                    </li>
                  ))}
                </ul>
              </Item>
            )}
          </Stagger>

          <form onSubmit={upload} className="card h-fit p-4 lg:sticky lg:top-[4.5rem]">
            <h2 className="flex items-center gap-2 font-semibold"><Upload className="h-4 w-4 text-accent" /> Raw clip</h2>
            <p className="mt-1 text-xs text-ink-2">
              Just the video. No CSV, no annotations, no metadata — the gate has to work it out from the frames, the same as it would on a
              fresh batch from the field.
            </p>

            <div
              onDragOver={(e) => { e.preventDefault(); setOver(true); }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files?.[0]; if (f) { setPicked(f); setError(null); } }}
              onClick={() => videoRef.current?.click()}
              className={`mt-3 grid cursor-pointer place-items-center gap-1 rounded-xl border-2 border-dashed px-4 py-7 text-center transition ${over ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong hover:bg-surface-2"}`}
            >
              <Upload className={`h-6 w-6 ${over ? "text-accent" : "text-muted"}`} />
              <p className="text-sm font-medium">Drop the raw clip here</p>
              <p className="text-xs text-muted">or click to pick a file</p>
            </div>

            {picked && (
              <p className="mt-3 flex items-center gap-2 rounded-lg bg-surface-2 px-2.5 py-1.5 text-xs">
                <FileVideo className="h-3.5 w-3.5 shrink-0 text-accent" />
                <span className="truncate">{picked.name}</span>
                <span className="num ml-auto shrink-0 text-muted">{(picked.size / 1e6).toFixed(1)} MB</span>
              </p>
            )}

            <input ref={videoRef} type="file" accept="video/*" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) { setPicked(f); setError(null); } }} />

            <label className="mt-3 block text-xs text-muted">Title (optional)
              <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Kitchen batch 12, clip 4"
                className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-sm text-ink" />
            </label>

            <label className="mt-3 block text-xs text-muted">Only the part showing&hellip; (optional)
              <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. a pizza"
                className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-sm text-ink" />
            </label>
            <p className="mt-1 text-[11px] text-muted">
              Name a subject and the cut narrows to where it is on camera <i>and</i> hands are working on it. If it is not in the
              clip at all, nothing is cut and you are told so &mdash; a prompt can only ever remove footage, never wave it through.
            </p>

            <button disabled={uploading || !picked} className="btn btn-primary mt-4 w-full py-2.5">
              {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scissors className="h-4 w-4" />} Cut and annotate it
            </button>

            <ol className="mt-4 space-y-1.5 border-t border-line pt-3 text-xs text-ink-2">
              {[topic.trim() ? `Find where “${topic.trim()}” is on camera` : "Find where the work starts and stops",
                "Cut the dead head and tail", "Measure hands, motion and exposure",
                "Write the first annotations with a confidence each", "Check its own annotations"].map((step, i) => (
                <li key={step} className="flex gap-2"><span className="num shrink-0 text-muted">{i + 1}.</span>{step}</li>
              ))}
            </ol>
            <p className="mt-2 text-[11px] text-muted">Then a person verifies. The AI is not asking to be trusted — it is asking to be checked.</p>
          </form>
        </div>
      </main>
    </div>
  );
}
