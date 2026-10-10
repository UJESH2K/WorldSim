"use client";

import { useEffect, useRef } from "react";
import { Coins, X } from "lucide-react";
import { formatUsd } from "@/lib/model";

export type SpendRequest = { what: string; seconds: number; rate: number; left: number; onYes: () => void };

/** Shown before anything that charges Reactor credit. "No" sends nothing at all. */
export function ConfirmSpend({ req, onClose }: { req: SpendRequest; onClose: () => void }) {
  const no = useRef<HTMLButtonElement>(null);
  useEffect(() => no.current?.focus(), []); // the safe choice has focus, so Enter never spends by accident
  const max = req.seconds * req.rate;
  const tooMuch = max > req.left;
  return (
    <div className="fixed inset-0 z-[70] grid place-items-center bg-black/65 p-4" onClick={onClose}>
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="spend-title"
        aria-describedby="spend-body"
        className="rise w-full max-w-md rounded-2xl border border-line bg-surface p-5 text-ink shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-caution/20 text-caution">
              <Coins className="h-5 w-5" aria-hidden />
            </span>
            <h2 id="spend-title" className="text-lg font-semibold">
              This will use Reactor credit
            </h2>
          </div>
          <button onClick={onClose} aria-label="Cancel" className="grid h-8 w-8 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p id="spend-body" className="mt-3 text-sm leading-relaxed text-ink-2">
          {req.what} runs in the real AI world, which is billed for every second a GPU is held for you.
        </p>
        <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
          <div className="rounded-lg bg-surface-2 p-3">
            <dt className="text-xs text-muted">At most</dt>
            <dd className="mt-1 text-xl font-semibold">{formatUsd(max)}</dd>
          </div>
          <div className="rounded-lg bg-surface-2 p-3">
            <dt className="text-xs text-muted">Time cap</dt>
            <dd className="mt-1 text-xl font-semibold">{req.seconds}s</dd>
          </div>
          <div className="rounded-lg bg-surface-2 p-3">
            <dt className="text-xs text-muted">Credit left</dt>
            <dd className="mt-1 text-xl font-semibold">{formatUsd(req.left)}</dd>
          </div>
        </dl>
        <p className="mt-3 text-xs text-muted">
          The session stops itself at the cap. Pressing Stop ends it sooner, and you only pay for the time used.
        </p>
        {tooMuch && (
          <p className="mt-2 text-sm text-collision" role="alert">
            That is more than the credit you have left. Lower the time cap first.
          </p>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button ref={no} onClick={onClose} className="rounded-lg border border-line-strong px-4 py-2 text-sm font-medium hover:bg-surface-2">
            No, don&apos;t spend
          </button>
          <button
            onClick={() => {
              req.onYes();
              onClose();
            }}
            disabled={tooMuch}
            className="rounded-lg bg-accent-fill px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-40"
          >
            Yes, spend up to {formatUsd(max)}
          </button>
        </div>
      </div>
    </div>
  );
}
