"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Compass, FileText, FlaskConical, ImagePlus, Keyboard, Loader2, Plane, ScanEye, Square, Wallet } from "lucide-react";
import { Logo } from "@/components/common";
import { StatTile, Timeline } from "@/components/sim/Charts";
import { InsightPanel, type Tab } from "@/components/sim/InsightPanel";
import { ShortcutsDialog, Toasts, Tour, TOUR, type Toast } from "@/components/sim/Overlays";
import { PilotPanel } from "@/components/sim/PilotPanel";
import { PlaceDialog } from "@/components/sim/PlaceDialog";
import { ConfirmSpend, type SpendRequest } from "@/components/sim/ConfirmSpend";
import { MAX_ZOOM, MIN_ZOOM, Viewport, type ViewState } from "@/components/sim/Viewport";
import { VERDICTS, formatUsd, useEngine, type Verdict } from "@/lib/engine";

// Held keys (keyboard and on-screen pad share this) -> one discrete action.
function keysToAction(k: Set<string>): string | null {
  const w = k.has("w"), s = k.has("s"), a = k.has("a"), d = k.has("d");
  const l = k.has("arrowleft"), r = k.has("arrowright");
  if (w && l) return "arc_left";
  if (w && r) return "arc_right";
  if (w) return "forward";
  if (s) return "back";
  if (l) return "yaw_left";
  if (r) return "yaw_right";
  if (a) return "left";
  if (d) return "right";
  if (k.has("arrowup")) return "up";
  if (k.has("arrowdown")) return "down";
  return null;
}
const FLIGHT_KEYS = ["w", "a", "s", "d", "arrowleft", "arrowright", "arrowup", "arrowdown"];

export default function Simulator() {
  const { state, catalog, offline, error, setError, post, refreshCatalog } = useEngine();
  const [placeOpen, setPlaceOpen] = useState(false);
  const [spend, setSpend] = useState<SpendRequest | null>(null);
  const [world, setWorld] = useState<"mock" | "reactor">("mock");
  const [scene, setScene] = useState("forest");
  const [seconds, setSeconds] = useState(90);
  const [tab, setTab] = useState<Tab>("safety");
  const [view, setView] = useState<ViewState>({ zoom: 1, x: 0, y: 0 });
  const [hud, setHud] = useState(true);
  const [fullscreen, setFullscreen] = useState(false);
  const [help, setHelp] = useState(false);
  const [tour, setTour] = useState<number | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [launching, setLaunching] = useState(false);
  const frameRef = useRef<HTMLDivElement>(null);
  const held = useRef(new Set<string>());
  const sent = useRef<string | null>(null);
  const lastAlert = useRef(-1);

  const f = state?.flight;
  const job = state?.job ?? null;
  const status = state?.status ?? "idle";
  const flying = job === "flight" && status === "running";
  const busy = status === "running" || status === "starting";
  const rate = catalog?.rate_per_second ?? 0.007;
  const decisions = f?.decisions ?? [];
  const last = decisions[decisions.length - 1];
  const verdict = (f?.assessment?.verdict as Verdict) ?? undefined;
  const activeScene = (busy ? f?.scene : null) ?? scene;
  const sceneSpec = catalog?.worlds.find((w) => w.key === activeScene);
  const activeWorld = (busy ? (f?.world ?? state?.config.world) : null) ?? world;
  const worldLabel = activeWorld === "reactor" ? "real AI world" : "practice world";

  // ---- phase, in words a visitor can follow
  let phase: "offline" | "idle" | "connecting" | "flying" | "busy" | "finished" = "idle";
  let phaseText =
    world === "reactor"
      ? "The real AI world generates every frame live from your chosen photo. Set a time cap, then press Fly; you will be asked before anything is charged."
      : catalog?.worlds.find((w) => w.key === scene)?.custom
        ? "Practice flies inside your own photo, free: forward moves in, turning pans across it. The real AI world builds new views beyond the photo."
        : "The practice world is free and runs on this laptop. Press Fly to take off.";
  if (offline) {
    phase = "offline";
    phaseText = "Start it from a terminal in the engine folder: .venv\\Scripts\\python -m uvicorn lucid.server:app --port 8765";
  } else if ((job === "flight" && status === "starting") || (launching && !job)) {
    phase = "connecting";
    phaseText = activeWorld === "reactor" ? "Connecting to the world model. Waiting for a GPU is free; billing starts at the first frame." : "Starting the practice world…";
  } else if (flying) {
    phase = "flying";
    phaseText = "Waiting for the first frame…";
  } else if (job === "autotune" || job === "train") {
    phase = "busy";
    phaseText = state?.detail || (job === "autotune" ? "Auto-tuning the autopilot…" : "Training a pilot…");
  } else if (decisions.length) {
    phase = "finished";
    phaseText =
      status === "stopped: budget" ? "Flight ended at your time cap." : status === "error" ? "Something went wrong. The log below has details." : "Flight finished. Press Fly to go again.";
  }

  // ---- actions
  const launch = useCallback(
    (confirmed: boolean) => {
      setView({ zoom: 1, x: 0, y: 0 });
      setTab("safety");
      setLaunching(true);
      setTimeout(() => setLaunching(false), 20000); // never spin forever
      post("flight", { world, scene, seconds, autopilot: true, confirm_spend: confirmed }).then((ok) => !ok && setLaunching(false));
    },
    [post, world, scene, seconds],
  );
  const creditLeft = state?.budget.spendable_usd ?? 0;
  // Anything billed asks first; "No" sends nothing to the engine.
  const fly = useCallback(() => {
    if (world !== "reactor") return launch(false);
    setSpend({ what: "This flight", seconds, rate, left: creditLeft, onYes: () => launch(true) });
  }, [world, seconds, rate, creditLeft, launch]);

  useEffect(() => {
    if (!job || !launching) return;
    const t = setTimeout(() => setLaunching(false), 0);
    return () => clearTimeout(t);
  }, [job, launching]);

  const sync = useCallback(() => {
    const action = keysToAction(held.current);
    if (action !== sent.current) {
      sent.current = action;
      post("control", { action });
    }
  }, [post]);
  const press = useCallback(
    (keys: string[]) => {
      keys.forEach((k) => held.current.add(k));
      sync();
    },
    [sync],
  );
  const release = useCallback(
    (keys: string[]) => {
      keys.forEach((k) => held.current.delete(k));
      sync();
    },
    [sync],
  );

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) document.exitFullscreen();
    else frameRef.current?.requestFullscreen?.();
  }, []);

  const snapshot = useCallback(async () => {
    try {
      const r = await fetch("/engine/frame.jpg", { cache: "no-store" });
      if (!r.ok) throw new Error();
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `lucid-${activeScene}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.jpg`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("No frame to save yet. Start a flight first.");
    }
  }, [activeScene, setError]);

  const zoomBy = useCallback((k: number) => setView((v) => ({ ...v, zoom: Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, v.zoom * k)), ...(v.zoom * k <= 1 ? { x: 0, y: 0 } : {}) })), []);

  // ---- effects
  useEffect(() => {
    const on = () => setFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);

  useEffect(() => {
    let seen = false;
    try {
      seen = localStorage.getItem("lucid-tour-done") === "1";
    } catch {}
    if (seen) return;
    const id = setTimeout(() => setTour(0), 700);
    return () => clearTimeout(id);
  }, []);

  const endTour = useCallback(() => {
    setTour(null);
    try {
      localStorage.setItem("lucid-tour-done", "1");
    } catch {}
  }, []);

  // New collisions and broken worlds get a toast; warnings stay in the Calls tab.
  useEffect(() => {
    const alerts = f?.alerts ?? [];
    const fresh = alerts.filter((a) => a.n > lastAlert.current && (a.verdict === "collision" || a.verdict === "anomaly"));
    if (alerts.length) lastAlert.current = Math.max(lastAlert.current, ...alerts.map((a) => a.n));
    if (!fresh.length) return;
    const add = fresh.slice(-2).map((a) => ({ id: a.n, verdict: a.verdict, text: a.reasons[0] ?? VERDICTS[a.verdict].plain }));
    const t = setTimeout(() => setToasts((ts) => [...ts, ...add].slice(-3)), 0);
    const timers = add.map((x) => setTimeout(() => setToasts((ts) => ts.filter((y) => y.id !== x.id)), 5000));
    return () => {
      clearTimeout(t);
      timers.forEach(clearTimeout);
    };
  }, [f?.alerts]);

  // Keyboard: flight keys while flying, view keys always, nothing while typing or in a dialog.
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el?.tagName === "INPUT" || el?.tagName === "SELECT" || el?.isContentEditable) return;
      if (e.key === "Escape") {
        setHelp(false);
        setPlaceOpen(false);
        setSpend(null);
        if (tour !== null) endTour();
        return;
      }
      if (help || placeOpen || spend || tour !== null || e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "?") return setHelp(true);
      if (k === "f") return toggleFullscreen();
      if (k === "h") return setHud((h) => !h);
      if (k === "c") return void snapshot();
      if (k === "+" || k === "=") return zoomBy(1.25);
      if (k === "-" || k === "_") return zoomBy(1 / 1.25);
      if (k === "0") return setView({ zoom: 1, x: 0, y: 0 });
      if (!flying) return;
      if (k === " ") {
        e.preventDefault();
        if (!e.repeat) post("autopilot", { on: !f?.autopilot });
        return;
      }
      if (FLIGHT_KEYS.includes(k)) {
        e.preventDefault();
        if (!e.repeat) press([k]);
      }
    };
    const up = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (held.current.has(k)) release([k]);
    };
    const blur = () => {
      held.current.clear();
      sync();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
    };
  }, [flying, help, placeOpen, spend, tour, f?.autopilot, post, press, release, sync, toggleFullscreen, snapshot, zoomBy, endTour]);

  const counts = f?.counts ?? {};
  const session = state?.usage?.backend === "reactor" && busy ? state.usage : null;

  return (
    <div className="sim flex min-h-screen flex-col overflow-x-clip bg-bg text-ink lg:h-screen">
      {/* ---------------- top bar ---------------- */}
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-surface px-4 py-2.5">
        <Link href="/" className="flex items-center gap-2" aria-label="Lucid home">
          <Logo />
          <span className="hidden rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted sm:inline">Simulator</span>
        </Link>

        <div className="order-last -mx-4 flex w-[calc(100%+2rem)] items-center gap-2 overflow-x-auto px-4 pb-1 lg:order-none lg:mx-0 lg:w-auto lg:min-w-0 lg:flex-1 lg:px-0 lg:pb-0 [&>*]:shrink-0">
          <div role="radiogroup" aria-label="World" className="flex rounded-lg bg-surface-2 p-0.5" data-tour="mode">
            {(
              [
                { id: "mock", label: "Practice world", note: "free" },
                { id: "reactor", label: "Real AI world", note: `$${(rate * 60).toFixed(2)}/min` },
              ] as const
            ).map((m) => (
              <button
                key={m.id}
                role="radio"
                aria-checked={world === m.id}
                disabled={busy}
                onClick={() => setWorld(m.id)}
                className={`rounded-md px-3 py-1.5 text-sm transition disabled:cursor-not-allowed ${
                  world === m.id ? "bg-surface text-ink shadow-sm ring-1 ring-line" : "text-muted hover:text-ink"
                }`}
              >
                {m.label.split(" ")[0]}
                <span className="hidden sm:inline"> {m.label.split(" ").slice(1).join(" ")}</span> <span className="text-xs text-muted">· {m.note}</span>
              </button>
            ))}
          </div>

          <div role="radiogroup" aria-label="Place" className="flex gap-1" data-tour="scene">
            {(catalog?.worlds ?? []).map((s) => (
              <button
                key={s.key}
                role="radio"
                aria-checked={scene === s.key}
                disabled={busy}
                onClick={() => setScene(s.key)}
                className={`flex items-center gap-2 rounded-lg border py-1 pl-1 pr-3 text-sm transition disabled:cursor-not-allowed ${
                  scene === s.key ? "border-accent bg-accent-soft text-ink" : "border-line text-muted hover:text-ink"
                }`}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={s.thumb} alt="" className="h-7 w-11 rounded object-cover" />
                {s.title}
              </button>
            ))}
            <button
              onClick={() => setPlaceOpen(true)}
              disabled={busy || offline}
              className="flex items-center gap-1.5 rounded-lg border border-dashed border-line-strong px-3 py-1 text-sm text-ink-2 transition hover:border-accent hover:text-ink disabled:opacity-40"
            >
              <ImagePlus className="h-4 w-4 text-accent" aria-hidden /> Your place
            </button>
          </div>

          {world === "reactor" && (
            <label className="flex items-center gap-2 rounded-lg border border-line px-2.5 py-1.5 text-sm">
              <span className="text-muted">Time cap</span>
              <input
                type="number"
                min={30}
                max={600}
                step={15}
                value={seconds}
                disabled={busy}
                onChange={(e) => setSeconds(Math.max(30, Math.min(600, Number(e.target.value) || 30)))}
                className="num w-14 bg-transparent text-ink outline-none"
                aria-label="Time cap in seconds"
              />
              <span className="text-muted">s · max {formatUsd(seconds * rate)}</span>
            </label>
          )}
        </div>

        <div className="ml-auto flex items-center gap-2">
          {busy ? (
            <button
              onClick={() => post("stop")}
              className="inline-flex items-center gap-2 rounded-lg bg-collision px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90"
              data-tour="fly"
            >
              <Square className="h-4 w-4" fill="currentColor" /> Stop
            </button>
          ) : (
            <button
              onClick={fly}
              disabled={offline}
              className="inline-flex items-center gap-2 rounded-lg bg-accent-fill px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-40"
              data-tour="fly"
            >
              <Plane className="h-4 w-4" /> Fly
            </button>
          )}
          <span
            className="hidden items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-xs text-ink-2 md:inline-flex"
            role="status"
          >
            <span
              className={`h-2 w-2 rounded-full ${busy ? "pulse" : ""}`}
              style={{ background: offline ? "#c2253d" : busy ? "#0ca30c" : "var(--muted)" }}
              aria-hidden
            />
            {offline ? "Engine offline" : status === "starting" || (launching && !job) ? "Starting" : busy ? (job === "flight" ? "Flying" : "Working") : "Ready"}
          </span>
          {session && (
            <span className="num hidden rounded-full border border-line px-2.5 py-1 text-xs text-ink-2 md:inline">
              {formatUsd(session.usd)} · {Math.round(session.seconds ?? 0)}/{session.cap_seconds}s
            </span>
          )}
          {state && (
            <span className="tip hidden items-center gap-1.5 text-xs text-muted lg:inline-flex" data-tip="Reactor credit left for the real AI world" data-tip-side="bottom" data-tip-align="end">
              <Wallet className="h-3.5 w-3.5" aria-hidden /> {formatUsd(state.budget.spendable_usd)} left
            </span>
          )}
          <Link
            href="/lab"
            aria-label="Pilot Lab"
            data-tip="Pilot Lab: improve a pilot from its mistakes"
            data-tip-side="bottom"
            data-tip-align="end"
            className="tip grid h-9 w-9 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink"
          >
            <FlaskConical className="h-4 w-4" />
          </Link>
          <Link
            href="/audit"
            aria-label="World audit"
            data-tip="World audit: where the AI world went wrong"
            data-tip-side="bottom"
            data-tip-align="end"
            className="tip grid h-9 w-9 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink"
          >
            <ScanEye className="h-4 w-4" />
          </Link>
          <Link
            href="/reports"
            aria-label="Flight reports"
            data-tip="Flight reports"
            data-tip-side="bottom"
            data-tip-align="end"
            className="tip grid h-9 w-9 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink"
          >
            <FileText className="h-4 w-4" />
          </Link>
          <button
            onClick={() => setTour(0)}
            aria-label="Take the tour"
            data-tip="Take the tour"
            data-tip-side="bottom"
            data-tip-align="end"
            className="tip grid h-9 w-9 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink"
          >
            <Compass className="h-4 w-4" />
          </button>
          <button
            onClick={() => setHelp(true)}
            aria-label="Keyboard shortcuts"
            data-tip="Keyboard shortcuts (?)"
            data-tip-side="bottom"
            data-tip-align="end"
            className="tip grid h-9 w-9 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink"
          >
            <Keyboard className="h-4 w-4" />
          </button>
        </div>
      </header>

      {error && (
        <div className="flex items-center justify-between gap-4 border-b border-collision/40 bg-collision/15 px-4 py-2 text-sm" role="alert">
          <span>{error}</span>
          <button onClick={() => setError("")} className="text-muted hover:text-ink">
            Dismiss
          </button>
        </div>
      )}

      {/* ---------------- workspace ---------------- */}
      <div className="grid flex-1 gap-4 p-4 lg:min-h-0 lg:grid-cols-[232px_minmax(0,1fr)_336px]">
        <aside className="order-2 lg:order-1 lg:min-h-0 lg:overflow-y-auto" aria-label="Pilot controls">
          <PilotPanel
            flying={flying}
            autopilot={f?.autopilot ?? true}
            onAutopilot={(on) => post("autopilot", { on })}
            press={press}
            release={release}
            currentAction={last?.action}
            pilot={last?.by}
            events={sceneSpec?.events ?? []}
            onEvent={(label) => post("event", { label })}
            brain={f?.brain ?? "reflex"}
            brainName={f?.brain_name}
            onBrain={(brain) => post("autopilot/brain", { brain })}
          />
        </aside>

        <main className="order-1 flex min-w-0 flex-col gap-3 lg:order-2 lg:min-h-0" aria-label="Flight view">
          <div className="aspect-[1664/960] w-full lg:aspect-auto lg:min-h-0 lg:flex-1">
            <Viewport
              frameRef={frameRef}
              view={view}
              setView={setView}
              hud={hud}
              onToggleHud={() => setHud((h) => !h)}
              fullscreen={fullscreen}
              onToggleFullscreen={toggleFullscreen}
              onSnapshot={snapshot}
              phase={phase}
              phaseText={phaseText}
              onFly={fly}
              canFly={!offline && !busy}
              droneBox={sceneSpec?.drone_box}
              hazards={f?.assessment?.hazards}
              verdict={verdict}
              reason={f?.assessment?.reasons?.[0]}
              pilot={last?.by}
              action={last?.action}
              why={last?.why}
              worldLabel={worldLabel}
              reportId={f?.report_id}
            />
          </div>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
            <StatTile label="Decisions" value={counts.decisions ?? 0} />
            <StatTile label="By autopilot" value={counts.autopilot ?? 0} />
            <StatTile label="By you" value={counts.human ?? 0} />
            <StatTile label="Warnings" value={counts.warning ?? 0} accent={VERDICTS.warning.color} />
            <StatTile label="Collisions" value={counts.collision ?? 0} accent={VERDICTS.collision.color} />
            <StatTile label="World broke" value={counts.anomaly ?? 0} accent={VERDICTS.anomaly.color} />
          </div>
          <div className="rounded-xl border border-line bg-surface p-3">
            <Timeline decisions={decisions} />
          </div>
        </main>

        <aside className="order-3 lg:min-h-0" aria-label="Insights">
          <InsightPanel
            tab={tab}
            setTab={setTab}
            state={state}
            busy={busy || offline}
            world={world}
            rate={rate}
            onAutotune={() =>
              world === "reactor"
                ? setSpend({
                    what: "Auto-tune",
                    seconds: 240,
                    rate,
                    left: creditLeft,
                    onYes: () => post("autotune", { world, scene, seconds: 240, confirm_spend: true }),
                  })
                : post("autotune", { world, scene, seconds })
            }
          />
        </aside>
      </div>

      {state && state.log.length > 0 && (
        <details className="border-t border-line bg-surface px-4 py-2 text-xs text-muted lg:hidden">
          <summary className="cursor-pointer">Engine log</summary>
          <div className="mt-2 max-h-40 overflow-auto font-mono">
            {state.log.slice().reverse().map((l, i) => (
              <div key={i}>{l}</div>
            ))}
          </div>
        </details>
      )}

      {busy && job !== "flight" && (
        <div className="pointer-events-none fixed bottom-4 left-1/2 z-40 flex -translate-x-1/2 items-center gap-2 rounded-full border border-line bg-surface px-4 py-2 text-sm shadow-xl">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {state?.detail || "Working…"}
        </div>
      )}

      <Toasts toasts={toasts} onDismiss={(id) => setToasts((ts) => ts.filter((t) => t.id !== id))} />
      {help && <ShortcutsDialog onClose={() => setHelp(false)} />}
      {spend && <ConfirmSpend req={spend} onClose={() => setSpend(null)} />}
      {placeOpen && (
        <PlaceDialog
          catalog={catalog}
          busy={busy}
          onClose={() => setPlaceOpen(false)}
          onCreated={async (key) => {
            await refreshCatalog();
            setScene(key);
            setPlaceOpen(false);
          }}
          onDeleted={async (key) => {
            await refreshCatalog();
            if (scene === key) setScene("forest");
          }}
        />
      )}
      {tour !== null && <Tour step={Math.min(tour, TOUR.length - 1)} onStep={setTour} onClose={endTour} />}
    </div>
  );
}
