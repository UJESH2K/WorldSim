"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { VERDICT_ICON } from "@/components/common";
import { VERDICTS, type Verdict } from "@/lib/engine";
import { Kbd } from "./PilotPanel";

// ---------------------------------------------------------------- guided tour
export const TOUR = [
  { target: "mode", title: "Pick a world", body: "Practice world is free and runs on this laptop. The real AI world is photoreal, generated live by LingBot World 2, and costs about $0.42 a minute." },
  { target: "scene", title: "Pick a place, or bring your own", body: "Each place starts from a real photo with the drone in it, and the world model builds everything else as it flies. Use “Your place” to upload a photo of the room you are in." },
  { target: "fly", title: "Take off", body: "Press Fly. In the real AI world you also set a time cap first, so a flight can never cost more than you agreed." },
  { target: "viewport", title: "Watch the flight", body: "The drone stays in the middle while the world is generated around it. Zoom, drag, take a snapshot or go full screen with the buttons in the corner." },
  { target: "pad", title: "Fly it yourself, or don't", body: "The autopilot flies by default. Hold any button here, or use WASD and the arrow keys, to take over. Space switches the autopilot back on." },
  { target: "events", title: "Make something happen", body: "Send a worker into the path or roll in fog, and watch how the drone and the referee react." },
  { target: "safety", title: "The referee", body: "Every step gets a call, from clear to collision, with the reason in plain words. Warnings collect under Calls." },
  { target: "timeline", title: "The whole flight at a glance", body: "One bar per decision. Taller and redder means more serious. Hover a bar to see what happened." },
];

export function Tour({ step, onStep, onClose }: { step: number; onStep: (n: number) => void; onClose: () => void }) {
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [cardH, setCardH] = useState(190);
  const card = useRef<HTMLDivElement>(null);
  const s = TOUR[step];

  useEffect(() => {
    const el = card.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setCardH(e.contentRect.height + 34));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const measure = () => {
      const el = document.querySelector(`[data-tour="${s.target}"]`);
      if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
      requestAnimationFrame(() => setRect(el ? el.getBoundingClientRect() : null));
    };
    const id = setTimeout(measure, 60);
    window.addEventListener("resize", measure);
    return () => {
      clearTimeout(id);
      window.removeEventListener("resize", measure);
    };
  }, [s.target]);

  const pad = 6;
  const cardW = Math.min(320, window.innerWidth - 24);
  const left = rect ? Math.min(Math.max(12, rect.left + rect.width / 2 - cardW / 2), window.innerWidth - cardW - 12) : 12;
  // Below the target if it fits, else above, else pinned to the bottom of the screen.
  let top = 24;
  if (rect) {
    if (rect.bottom + 12 + cardH <= window.innerHeight) top = rect.bottom + 12;
    else if (rect.top - 12 - cardH >= 0) top = rect.top - 12 - cardH;
    else top = window.innerHeight - cardH - 16;
  }

  return (
    <div className="fixed inset-0 z-[60]" role="dialog" aria-modal="true" aria-labelledby="tour-title">
      {rect ? (
        <div
          className="pointer-events-none fixed rounded-xl ring-2 ring-accent transition-all duration-200"
          style={{
            left: rect.left - pad,
            top: rect.top - pad,
            width: rect.width + pad * 2,
            height: rect.height + pad * 2,
            boxShadow: "0 0 0 9999px rgba(0,0,0,0.62)",
          }}
        />
      ) : (
        <div className="fixed inset-0 bg-black/60" />
      )}
      <div ref={card} className="rise fixed rounded-xl border border-line bg-surface p-4 text-ink shadow-2xl" style={{ left, top, width: cardW }}>
        <div className="flex items-center justify-between">
          <span className="num text-xs text-muted">
            Step {step + 1} of {TOUR.length}
          </span>
          <button onClick={onClose} aria-label="Close the tour" className="grid h-7 w-7 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </div>
        <h2 id="tour-title" className="mt-1 font-semibold">
          {s.title}
        </h2>
        <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{s.body}</p>
        <div className="mt-4 flex items-center justify-between">
          <button onClick={onClose} className="text-sm text-muted hover:text-ink">
            Skip tour
          </button>
          <div className="flex gap-2">
            {step > 0 && (
              <button onClick={() => onStep(step - 1)} className="rounded-lg border border-line-strong px-3 py-1.5 text-sm hover:bg-surface-2">
                Back
              </button>
            )}
            <button
              autoFocus
              onClick={() => (step + 1 < TOUR.length ? onStep(step + 1) : onClose())}
              className="rounded-lg bg-accent-fill px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
            >
              {step + 1 < TOUR.length ? "Next" : "Start flying"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- shortcuts
const SHORTCUTS: { keys: string[]; what: string }[] = [
  { keys: ["W"], what: "Fly forward" },
  { keys: ["S"], what: "Fly back" },
  { keys: ["A", "D"], what: "Slide left / right" },
  { keys: ["←", "→"], what: "Turn left / right" },
  { keys: ["W", "+", "←"], what: "Curve while flying forward" },
  { keys: ["↑", "↓"], what: "Climb / descend" },
  { keys: ["Space"], what: "Autopilot on / off" },
  { keys: ["F"], what: "Full screen" },
  { keys: ["+", "−"], what: "Zoom in / out (or mouse wheel)" },
  { keys: ["0"], what: "Reset zoom" },
  { keys: ["H"], what: "Show / hide the overlay" },
  { keys: ["C"], what: "Save a snapshot" },
  { keys: ["?"], what: "This help" },
];

export function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => close.current?.focus(), []);
  return (
    <div className="fixed inset-0 z-[60] grid place-items-center bg-black/60 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="keys-title"
        className="rise w-full max-w-md rounded-2xl border border-line bg-surface p-5 text-ink shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 id="keys-title" className="text-lg font-semibold">
            Keyboard shortcuts
          </h2>
          <button ref={close} onClick={onClose} aria-label="Close" className="grid h-8 w-8 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mt-1 text-sm text-muted">Flight keys work while a flight is running. Hold a key to keep moving.</p>
        <dl className="mt-4 divide-y divide-line">
          {SHORTCUTS.map((s) => (
            <div key={s.what} className="flex items-center justify-between gap-4 py-2 text-sm">
              <dt className="text-ink-2">{s.what}</dt>
              <dd className="flex gap-1">
                {s.keys.map((k, i) => (k === "+" && s.keys.length === 3 ? <span key={i} className="text-muted">+</span> : <Kbd key={i}>{k}</Kbd>))}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- toasts
export type Toast = { id: number; verdict: Verdict; text: string };

export function Toasts({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  return (
    <div className="pointer-events-none fixed inset-x-0 top-16 z-50 flex flex-col items-center gap-2 px-4" aria-live="assertive">
      {toasts.map((t) => {
        const Icon = VERDICT_ICON[t.verdict];
        return (
          <div
            key={t.id}
            className="rise pointer-events-auto flex w-full max-w-md items-center gap-3 rounded-xl border border-line bg-surface p-3 text-ink shadow-2xl"
            style={{ borderLeft: `4px solid ${VERDICTS[t.verdict].color}` }}
          >
            <Icon className="h-5 w-5 shrink-0" style={{ color: VERDICTS[t.verdict].color }} aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">{VERDICTS[t.verdict].label} called</p>
              <p className="truncate text-sm text-ink-2">{t.text}</p>
            </div>
            <button onClick={() => onDismiss(t.id)} aria-label="Dismiss" className="grid h-7 w-7 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink">
              <X className="h-4 w-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
