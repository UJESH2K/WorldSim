"use client";

import { useEffect, useState } from "react";
import { Pause, Play } from "lucide-react";
import showcase from "@/data/showcase.json";
import { FrameOverlay, VerdictBadge } from "@/components/common";
import type { Hazard, Verdict } from "@/lib/model";

const REEL = ["hero", "ranger-at-drone", "worker-aisle", "world-broke"];
const items = REEL.map((id) => showcase.find((s) => s.id === id)!).filter(Boolean);

/** A few real frames from LingBot flights, each with the referee's call drawn on it. */
export function HeroReel() {
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(true);

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => setI((x) => (x + 1) % items.length), 4000);
    return () => clearInterval(id);
  }, [playing]);

  const it = items[i];
  return (
    <figure className="overflow-hidden rounded-2xl border border-line bg-surface shadow-[0_24px_60px_-28px_rgba(11,11,11,0.35)]">
      <div className="relative bg-[#0b0c0e]" style={{ aspectRatio: `${it.width} / ${it.height}` }}>
        {items.map((s, k) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={s.id}
            src={s.src}
            alt={s.caption}
            className="absolute inset-0 h-full w-full object-cover transition-opacity duration-700"
            style={{ opacity: k === i ? 1 : 0 }}
          />
        ))}
        <FrameOverlay droneBox={it.droneBox} hazards={it.hazards as Hazard[]} verdict={it.verdict as Verdict} />
        <div className="absolute left-3 top-3 flex items-center gap-2">
          <VerdictBadge verdict={it.verdict as Verdict} />
          {it.reasons[0] && <span className="rounded-md bg-black/60 px-2 py-1 text-xs text-white backdrop-blur">{it.reasons[0]}</span>}
        </div>
        <span className="absolute right-3 top-3 rounded-md bg-black/60 px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-white/90 backdrop-blur">
          generated live · LingBot World 2
        </span>
      </div>
      <figcaption className="flex items-center justify-between gap-4 px-4 py-3">
        <p className="text-sm text-ink-2">{it.caption}</p>
        <div className="flex shrink-0 items-center gap-2">
          {items.map((s, k) => (
            <button
              key={s.id}
              onClick={() => {
                setI(k);
                setPlaying(false);
              }}
              aria-label={`Show frame ${k + 1}: ${s.caption}`}
              aria-current={k === i}
              className="h-2 w-2 rounded-full transition-all"
              style={{ background: k === i ? "var(--ink)" : "var(--line-strong)", width: k === i ? 18 : 8 }}
            />
          ))}
          <button
            onClick={() => setPlaying((p) => !p)}
            aria-label={playing ? "Pause the slideshow" : "Play the slideshow"}
            className="ml-1 grid h-7 w-7 place-items-center rounded-full border border-line text-ink-2 hover:bg-surface-2"
          >
            {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          </button>
        </div>
      </figcaption>
    </figure>
  );
}
