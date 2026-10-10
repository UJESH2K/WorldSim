"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { Camera, Layers, Loader2, Maximize, Minimize, Plane, ScanSearch, ZoomIn, ZoomOut } from "lucide-react";
import { FrameOverlay, VerdictBadge } from "@/components/common";
import { ACTION_LABEL, STREAM_URL, type Hazard, type Verdict } from "@/lib/engine";

export type ViewState = { zoom: number; x: number; y: number };
export const MIN_ZOOM = 1;
export const MAX_ZOOM = 4;

type Props = {
  frameRef: RefObject<HTMLDivElement | null>;
  view: ViewState;
  setView: (v: ViewState | ((v: ViewState) => ViewState)) => void;
  hud: boolean;
  onToggleHud: () => void;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
  onSnapshot: () => void;
  phase: "offline" | "idle" | "connecting" | "flying" | "busy" | "finished";
  phaseText: string;
  onFly: () => void;
  canFly: boolean;
  droneBox?: number[];
  hazards?: Hazard[];
  verdict?: Verdict;
  reason?: string;
  pilot?: string;
  action?: string;
  why?: string;
  worldLabel: string;
  reportId?: string | null;
};

function ToolButton({ label, onClick, children, active = false }: { label: string; onClick: () => void; children: React.ReactNode; active?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={active}
      data-tip={label}
      className={`tip grid h-8 w-8 place-items-center rounded-lg transition hover:bg-white/10 sm:h-9 sm:w-9 ${active ? "bg-white/15 text-white" : "text-white/80"}`}
    >
      {children}
    </button>
  );
}

// The ref is pulled out of props: React treats a props object that carries a ref as a ref.
export function Viewport({ frameRef, ...p }: Props) {
  const { view, setView } = p;
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const [streamOn, setStreamOn] = useState(false);
  const [hasFrame, setHasFrame] = useState(false);
  const [dragging, setDragging] = useState(false);

  // The MJPEG never finishes loading; attach it after window load so the page does.
  useEffect(() => {
    const on = () => setStreamOn(true);
    if (document.readyState === "complete") {
      const id = setTimeout(on, 0);
      return () => clearTimeout(id);
    }
    window.addEventListener("load", on, { once: true });
    return () => window.removeEventListener("load", on);
  }, []);

  const clampPan = useCallback((v: ViewState): ViewState => {
    const el = box.current;
    if (!el || v.zoom <= 1) return { zoom: Math.max(MIN_ZOOM, v.zoom), x: 0, y: 0 };
    const mx = ((v.zoom - 1) * el.clientWidth) / 2;
    const my = ((v.zoom - 1) * el.clientHeight) / 2;
    return { zoom: v.zoom, x: Math.max(-mx, Math.min(mx, v.x)), y: Math.max(-my, Math.min(my, v.y)) };
  }, []);

  // Wheel zooms around the cursor. Non-passive so the page does not scroll underneath.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const cx = e.clientX - r.left - r.width / 2;
      const cy = e.clientY - r.top - r.height / 2;
      setView((v) => {
        const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, v.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
        const k = zoom / v.zoom;
        return clampPan({ zoom, x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k });
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [setView, clampPan]);

  const zoomBy = (f: number) => setView((v) => clampPan({ ...v, zoom: Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, v.zoom * f)) }));
  const showStage = p.phase === "flying" || p.phase === "busy" || p.phase === "finished";

  return (
    <div ref={frameRef} className="relative flex h-full min-h-0 w-full flex-col overflow-hidden rounded-xl border border-line bg-black" data-tour="viewport">
      <div
        ref={box}
        className={`relative min-h-0 flex-1 overflow-hidden ${view.zoom > 1 ? "cursor-grab active:cursor-grabbing" : ""}`}
        onPointerDown={(e) => {
          if (view.zoom <= 1 || (e.target as HTMLElement).closest("button")) return;
          (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
          drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
          setDragging(true);
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (!d) return;
          setView(clampPan({ zoom: view.zoom, x: d.vx + e.clientX - d.x, y: d.vy + e.clientY - d.y }));
        }}
        onPointerUp={() => {
          drag.current = null;
          setDragging(false);
        }}
        onPointerCancel={() => {
          drag.current = null;
          setDragging(false);
        }}
        onDoubleClick={() => setView((v) => (v.zoom > 1 ? { zoom: 1, x: 0, y: 0 } : clampPan({ zoom: 2, x: 0, y: 0 })))}
      >
        {/* The stage keeps the world model's aspect ratio and is centred in whatever space is left. */}
        <div className="absolute inset-0 grid place-items-center" style={{ containerType: "size" }}>
          <div
            className="relative"
            style={{
              aspectRatio: "1664 / 960",
              width: "min(100cqw, calc(100cqh * 1664 / 960))",
              transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`,
              transition: dragging ? "none" : "transform 120ms ease-out",
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={streamOn ? STREAM_URL : undefined}
              alt={`Live view of the drone in the ${p.worldLabel}`}
              onLoad={() => setHasFrame(true)}
              className="absolute inset-0 h-full w-full select-none object-cover"
              style={{ opacity: hasFrame && showStage ? 1 : 0 }}
              draggable={false}
            />
            {p.hud && showStage && hasFrame && (
              <FrameOverlay droneBox={p.droneBox} hazards={p.hazards} verdict={p.verdict} showLabels={view.zoom < 2.5} />
            )}
          </div>
        </div>

        {/* HUD chips: outside the zoom transform so they stay readable. */}
        {p.hud && p.phase === "flying" && p.verdict && (
          <div className="pointer-events-none absolute left-3 top-3 flex max-w-[70%] flex-wrap items-center gap-2" role="status" aria-live="polite">
            <VerdictBadge verdict={p.verdict} size="lg" />
            {p.reason && <span className="hidden rounded-md bg-black/65 px-2.5 py-1.5 text-sm text-white backdrop-blur sm:inline">{p.reason}</span>}
          </div>
        )}
        {p.hud && p.phase === "flying" && (
          <div className="pointer-events-none absolute right-3 top-3 rounded-lg bg-black/65 px-3 py-2 text-right text-white backdrop-blur">
            <div className="text-[11px] uppercase tracking-wider text-white/60">{p.pilot === "human" ? "You are flying" : p.pilot === "autopilot" ? "Autopilot" : "Hovering"}</div>
            <div className="text-sm font-semibold">{ACTION_LABEL[p.action ?? ""] ?? "—"}</div>
            {p.why && p.pilot === "autopilot" && <div className="hidden max-w-56 truncate text-xs text-white/70 sm:block">{p.why}</div>}
          </div>
        )}

        {/* States */}
        {(p.phase === "idle" || p.phase === "offline") && (
          <div className="absolute inset-0 grid place-items-center bg-[radial-gradient(ellipse_at_center,rgba(57,135,229,0.12),transparent_60%)] p-6 text-center">
            <div className="max-w-md">
              <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-white/5 ring-1 ring-white/10">
                <Plane className="h-6 w-6 text-white/80" aria-hidden />
              </div>
              <h2 className="mt-4 text-xl font-semibold text-white">{p.phase === "offline" ? "The engine is not running" : "Ready for take-off"}</h2>
              <p className="mt-2 text-sm leading-relaxed text-white/65">{p.phaseText}</p>
              {p.phase === "idle" && (
                <button
                  onClick={p.onFly}
                  disabled={!p.canFly}
                  className="mt-5 inline-flex items-center gap-2 rounded-lg bg-accent-fill px-5 py-2.5 font-medium text-white transition hover:opacity-90 disabled:opacity-40"
                >
                  <Plane className="h-4 w-4" /> Fly in the {p.worldLabel}
                </button>
              )}
            </div>
          </div>
        )}
        {(p.phase === "connecting" || (p.phase === "flying" && !hasFrame)) && (
          <div className="absolute inset-0 grid place-items-center bg-black/60 p-6 text-center">
            <div>
              <Loader2 className="mx-auto h-8 w-8 animate-spin text-white/80" aria-hidden />
              <p className="mt-3 font-medium text-white">{p.phaseText}</p>
            </div>
          </div>
        )}
        {p.phase === "finished" && (
          <div className="absolute inset-x-0 bottom-16 flex justify-center">
            <span className="flex items-center gap-3 rounded-full bg-black/75 py-1.5 pl-4 pr-1.5 text-sm text-white backdrop-blur">
              {p.phaseText}
              {p.reportId && (
                <a href={`/report/${p.reportId}`} className="rounded-full bg-white px-3 py-1 font-medium text-[#0b0c0e] hover:opacity-90">
                  View flight report
                </a>
              )}
            </span>
          </div>
        )}

        {/* Toolbar */}
        <div
          className="absolute bottom-3 right-3 flex items-center gap-0.5 rounded-xl bg-black/70 p-1 ring-1 ring-white/10 backdrop-blur"
          role="toolbar"
          aria-label="View controls"
          data-tour="toolbar"
        >
          <ToolButton label="Zoom out (−)" onClick={() => zoomBy(1 / 1.25)}>
            <ZoomOut className="h-4 w-4" />
          </ToolButton>
          <button
            type="button"
            onClick={() => setView({ zoom: 1, x: 0, y: 0 })}
            className="tip num w-12 rounded-md py-1.5 text-center text-xs text-white/80 hover:bg-white/10"
            data-tip="Reset zoom (0)"
            aria-label={`Zoom ${Math.round(view.zoom * 100)} percent. Reset zoom`}
          >
            {Math.round(view.zoom * 100)}%
          </button>
          <ToolButton label="Zoom in (+)" onClick={() => zoomBy(1.25)}>
            <ZoomIn className="h-4 w-4" />
          </ToolButton>
          <ToolButton label="Fit to view (0)" onClick={() => setView({ zoom: 1, x: 0, y: 0 })}>
            <ScanSearch className="h-4 w-4" />
          </ToolButton>
          <span className="mx-1 h-5 w-px bg-white/15" aria-hidden />
          <ToolButton label={p.hud ? "Hide overlay (H)" : "Show overlay (H)"} onClick={p.onToggleHud} active={p.hud}>
            <Layers className="h-4 w-4" />
          </ToolButton>
          <ToolButton label="Save a snapshot (C)" onClick={p.onSnapshot}>
            <Camera className="h-4 w-4" />
          </ToolButton>
          <ToolButton label={p.fullscreen ? "Exit full screen (F)" : "Full screen (F)"} onClick={p.onToggleFullscreen} active={p.fullscreen}>
            {p.fullscreen ? <Minimize className="h-4 w-4" /> : <Maximize className="h-4 w-4" />}
          </ToolButton>
        </div>
        {view.zoom > 1 && (
          <span className="pointer-events-none absolute bottom-3 left-3 rounded-md bg-black/60 px-2 py-1 text-xs text-white/80">
            Drag to look around · double-click to reset
          </span>
        )}
      </div>
    </div>
  );
}
