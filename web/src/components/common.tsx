import { CircleAlert, CircleCheck, Ghost, OctagonAlert, TriangleAlert, type LucideIcon } from "lucide-react";
import { VERDICTS, type Hazard, type Verdict } from "@/lib/model";

export const VERDICT_ICON: Record<Verdict, LucideIcon> = {
  clear: CircleCheck,
  caution: CircleAlert,
  warning: TriangleAlert,
  collision: OctagonAlert,
  anomaly: Ghost,
};

export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 font-semibold tracking-tight ${className}`}>
      <svg viewBox="0 0 32 32" className="h-6 w-6" aria-hidden>
        <rect x="1" y="1" width="30" height="30" rx="8" fill="currentColor" opacity="0.12" />
        <circle cx="9" cy="9" r="3.2" fill="none" stroke="currentColor" strokeWidth="2" />
        <circle cx="23" cy="9" r="3.2" fill="none" stroke="currentColor" strokeWidth="2" />
        <circle cx="9" cy="23" r="3.2" fill="none" stroke="currentColor" strokeWidth="2" />
        <circle cx="23" cy="23" r="3.2" fill="none" stroke="currentColor" strokeWidth="2" />
        <path d="M11.5 11.5 L20.5 20.5 M20.5 11.5 L11.5 20.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        <circle cx="16" cy="16" r="2.4" fill="var(--accent)" />
      </svg>
      Lucid
    </span>
  );
}

/** Status pill: icon + label + colour, so meaning never rides on colour alone. */
export function VerdictBadge({ verdict, size = "md", className = "" }: { verdict: Verdict; size?: "sm" | "md" | "lg"; className?: string }) {
  const v = VERDICTS[verdict];
  const Icon = VERDICT_ICON[verdict];
  // Dark text everywhere except on red: every pairing clears 4.5:1 (white on green or violet would not).
  const dark = verdict !== "collision";
  const pad = size === "lg" ? "px-3 py-1.5 text-sm" : size === "sm" ? "px-1.5 py-0.5 text-[11px]" : "px-2 py-1 text-xs";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md font-semibold uppercase tracking-wide ${pad} ${className}`}
      style={{ background: v.color, color: dark ? "#0b0b0b" : "#ffffff" }}
    >
      <Icon aria-hidden className={size === "lg" ? "h-4 w-4" : "h-3.5 w-3.5"} strokeWidth={2.4} />
      {v.label}
    </span>
  );
}

const ZONE_COLOR: Record<Hazard["zone"], string> = {
  touching: "#c2253d",
  close: "#f06a1d",
  ahead: "#f06a1d",
  behind: "#fab219",
  far: "#fab219",
};

export const ZONE_LABEL: Record<Hazard["zone"], string> = {
  touching: "touching",
  close: "very close",
  ahead: "in the path",
  behind: "between camera and drone",
  far: "in view",
};

/** Boxes drawn in normalised coordinates over a frame: the drone and anything the referee saw. */
export function FrameOverlay({
  droneBox,
  hazards,
  verdict,
  showLabels = true,
}: {
  droneBox?: number[];
  hazards?: Hazard[];
  verdict?: Verdict;
  showLabels?: boolean;
}) {
  const color = verdict ? VERDICTS[verdict].color : "#ffffff";
  // Only what matters: things behind the drone's path are not drawn, distant ones get a faint
  // unlabelled box, and labels are kept for real risks so a crowded room stays readable.
  const shown = (hazards ?? []).filter((h) => h.zone !== "behind");
  const risky = (h: Hazard) => h.zone === "touching" || h.zone === "close" || h.zone === "ahead";
  return (
    <>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
        {droneBox && (
          <rect
            x={droneBox[0] * 100}
            y={droneBox[1] * 100}
            width={droneBox[2] * 100}
            height={droneBox[3] * 100}
            rx="1"
            fill="none"
            stroke={color}
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
        )}
        {shown.map((h, i) => (
          <rect
            key={i}
            x={h.box[0] * 100}
            y={h.box[1] * 100}
            width={(h.box[2] - h.box[0]) * 100}
            height={(h.box[3] - h.box[1]) * 100}
            fill="none"
            stroke={ZONE_COLOR[h.zone]}
            strokeWidth={risky(h) ? 2 : 1}
            strokeOpacity={risky(h) ? 1 : 0.45}
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      {showLabels &&
        shown.filter(risky).map((h, i) => (
          <span
            key={i}
            className="pointer-events-none absolute -translate-y-full rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide"
            style={{
              left: `${h.box[0] * 100}%`,
              top: `${h.box[1] * 100}%`,
              background: ZONE_COLOR[h.zone],
              color: h.zone === "touching" ? "#ffffff" : "#0b0b0b", // 4.5:1 or better on every zone colour
            }}
          >
            {h.label} · {ZONE_LABEL[h.zone]}
          </span>
        ))}
    </>
  );
}
