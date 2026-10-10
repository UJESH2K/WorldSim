"use client";

import { useState } from "react";
import type { AuditEvent } from "@/lib/lab";

type Point = { k: number; scene: number; drone: number; ok: boolean };

const KIND_MARK: Record<AuditEvent["kind"], string> = {
  "scene drift": "S",
  "scene cut": "C",
  "colour shift": "L",
  "drone morphed": "D",
  "pop-in": "P",
};

/** Scene and drone similarity per chunk against their thresholds. Untrusted chunks are shaded,
 *  events marked on top, re-anchors drawn as vertical rules. Two series, labelled at their ends. */
export function SignalChart({
  points,
  events,
  anchors = [],
  sceneMin,
  droneMin,
  selected,
  onSelect,
}: {
  points: Point[];
  events: Pick<AuditEvent, "chunk" | "kind">[];
  anchors?: { chunk: number }[];
  sceneMin: number;
  droneMin: number;
  selected?: number | null;
  onSelect?: (k: number) => void;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 800;
  const H = 220;
  const P = { l: 34, r: 56, t: 22, b: 22 };
  const k0 = points[0]?.k ?? 0;
  const k1 = points[points.length - 1]?.k ?? 1;
  const lo = 0.5;
  const hi = 1.0;
  const x = (k: number) => P.l + ((k - k0) / Math.max(1, k1 - k0)) * (W - P.l - P.r);
  const y = (v: number) => P.t + (1 - (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * (H - P.t - P.b);
  const step = (W - P.l - P.r) / Math.max(1, k1 - k0);
  const line = (key: "scene" | "drone") => points.map((p) => `${x(p.k).toFixed(1)},${y(p[key]).toFixed(1)}`).join(" ");
  const at = hover ?? selected ?? null;
  const hp = at != null ? points.find((p) => p.k === at) : null;
  const last = points[points.length - 1];

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-56 w-full cursor-crosshair"
        role="img"
        aria-label="Scene and drone similarity to the seed photo, per chunk"
        onMouseMove={(e) => {
          if (!points.length) return;
          const r = e.currentTarget.getBoundingClientRect();
          const px = ((e.clientX - r.left) / r.width) * W;
          const k = Math.round(k0 + ((px - P.l) / (W - P.l - P.r)) * (k1 - k0));
          setHover(Math.max(k0, Math.min(k1, k)));
        }}
        onMouseLeave={() => setHover(null)}
        onClick={() => hover != null && onSelect?.(hover)}
      >
        {/* untrusted chunks */}
        {points.map((p) =>
          p.ok ? null : <rect key={`u${p.k}`} x={x(p.k) - step / 2} y={P.t} width={Math.max(1, step)} height={H - P.t - P.b} fill="var(--collision)" opacity="0.12" />,
        )}
        {[0.5, 0.75, 1].map((v) => (
          <g key={v}>
            <line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} stroke="var(--line)" />
            <text x={P.l - 6} y={y(v) + 3} fontSize="10" textAnchor="end" fill="var(--muted)">{v.toFixed(2)}</text>
          </g>
        ))}
        <line x1={P.l} x2={W - P.r} y1={y(sceneMin)} y2={y(sceneMin)} stroke="var(--warning)" strokeDasharray="4 4" />
        <text x={W - P.r + 4} y={y(sceneMin) + 3} fontSize="10" fill="var(--warning)">limit {sceneMin}</text>
        {Math.abs(droneMin - sceneMin) > 0.015 && (
          <line x1={P.l} x2={W - P.r} y1={y(droneMin)} y2={y(droneMin)} stroke="var(--warning)" strokeDasharray="2 5" opacity="0.7" />
        )}
        {anchors.map((a) => (
          <g key={`a${a.chunk}`}>
            <line x1={x(a.chunk)} x2={x(a.chunk)} y1={P.t - 8} y2={H - P.b} stroke="var(--clear)" strokeWidth="2" />
            <text x={x(a.chunk) + 3} y={P.t - 10} fontSize="10" fill="var(--clear)">re-anchor</text>
          </g>
        ))}
        <polyline points={line("scene")} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" />
        <polyline points={line("drone")} fill="none" stroke="var(--anomaly)" strokeWidth="2" strokeLinejoin="round" />
        {last && (
          <>
            <text x={x(last.k) + 6} y={y(last.scene) + 4} fontSize="11" fill="var(--accent)" fontWeight="600">scene</text>
            <text x={x(last.k) + 6} y={y(last.drone) + 4 + (Math.abs(y(last.drone) - y(last.scene)) < 12 ? 12 : 0)} fontSize="11" fill="var(--anomaly)" fontWeight="600">drone</text>
          </>
        )}
        {events.map((e, i) => (
          <g key={`e${i}`} transform={`translate(${x(e.chunk)}, ${H - P.b + 2})`}>
            <rect x="-7" y="0" width="14" height="14" rx="3" fill="var(--collision)" />
            <text y="10.5" fontSize="9" textAnchor="middle" fill="#fff" fontWeight="700">{KIND_MARK[e.kind]}</text>
          </g>
        ))}
        {at != null && (
          <line x1={x(at)} x2={x(at)} y1={P.t} y2={H - P.b} stroke="var(--ink-2)" strokeWidth="1" />
        )}
      </svg>
      {hp && (
        <div className="num pointer-events-none absolute right-2 top-0 rounded-md border border-line bg-surface px-2 py-1 text-[11px]">
          chunk {hp.k} · scene <b className="text-accent">{hp.scene.toFixed(2)}</b> · drone <b style={{ color: "var(--anomaly)" }}>{hp.drone.toFixed(2)}</b>
          {hp.ok ? "" : " · untrusted"}
        </div>
      )}
    </div>
  );
}
