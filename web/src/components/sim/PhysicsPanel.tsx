"use client";

import Link from "next/link";
import { Atom, BatteryMedium, FileText, Gauge, MoveUp, Navigation, RotateCw, Scale, Zap } from "lucide-react";
import type { Decision, Flight } from "@/lib/model";
import { Trace } from "./Charts";

const RPM_MAX = 6685; // w_max 700 rad/s

function Readout({ icon: Icon, label, value, unit }: { icon: typeof Gauge; label: string; value: string; unit: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2">
      <div className="flex items-center gap-1.5 text-xs text-ink-2">
        <Icon className="h-3.5 w-3.5" aria-hidden /> {label}
      </div>
      <div className="mt-0.5 text-xl font-semibold tracking-tight">
        {value}
        <span className="ml-1 text-xs font-normal text-muted">{unit}</span>
      </div>
    </div>
  );
}

/** The drone's physical state from the quadrotor model, and the render-vs-physics weight. */
export function PhysicsPanel({ flight, flying }: { flight?: Flight; flying: boolean }) {
  const ph = flight?.physics ?? {};
  const cal = flight?.calibration ?? {};
  const decisions: Decision[] = flight?.decisions ?? [];
  const speeds = decisions.slice(-80).map((d) => d.physics?.speed_ms ?? 0);
  const has = ph.speed_ms !== undefined;
  const fmt = (v: number | undefined, d = 1) => (v === undefined ? "—" : v.toFixed(d));

  return (
    <div id="panel-physics" role="tabpanel" aria-labelledby="tab-physics" className="flex flex-col gap-4">
      <section className="rounded-xl border border-line bg-surface p-4">
        <h2 className="flex items-center gap-2 font-semibold">
          <Atom className="h-4 w-4 text-accent" aria-hidden /> Real physics underneath
        </h2>
        <p className="mt-1.5 text-sm leading-relaxed text-ink-2">
          A 6-DoF quadrotor (Phantom 2 class: 1.0 kg, 350 mm) simulated in {ph.engine ?? "MuJoCo"} at 400 Hz, flown by a
          PX4-style controller, decides where the drone actually is. The world model only draws it.
        </p>
      </section>

      {!has && <p className="rounded-xl border border-dashed border-line p-4 text-sm text-muted">Start a flight to see live physics.</p>}
      {has && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Readout icon={Gauge} label="Speed" value={fmt(ph.speed_ms)} unit="m/s" />
            <Readout icon={MoveUp} label="Altitude" value={fmt(ph.altitude_m, 2)} unit="m" />
            <Readout icon={Navigation} label="Heading" value={fmt(ph.heading_deg, 0)} unit="°" />
            <Readout icon={RotateCw} label="Tilt" value={fmt(ph.tilt_deg)} unit="°" />
            <Readout icon={BatteryMedium} label="Battery" value={fmt(ph.battery_pct, 1)} unit="%" />
            <Readout icon={Zap} label="Power" value={fmt(ph.power_w, 0)} unit="W" />
          </div>
          <section aria-labelledby="motors-h">
            <h3 id="motors-h" className="text-sm text-ink-2">
              Motor speeds
            </h3>
            <div className="mt-2 grid grid-cols-4 gap-2">
              {(ph.motor_rpm ?? [0, 0, 0, 0]).map((rpm, i) => (
                <div key={i} className="text-center">
                  <div className="relative mx-auto h-16 w-3 overflow-hidden rounded-full bg-surface-2" role="meter" aria-label={`Motor ${i + 1}`} aria-valuenow={rpm} aria-valuemin={0} aria-valuemax={RPM_MAX}>
                    <div className="absolute inset-x-0 bottom-0 rounded-full bg-accent" style={{ height: `${Math.min(100, (rpm / RPM_MAX) * 100)}%` }} />
                  </div>
                  <div className="num mt-1 text-[11px] text-muted">{rpm}</div>
                </div>
              ))}
            </div>
            <p className="mt-1 text-[11px] text-muted">rpm · front-left, front-right, back-right, back-left</p>
          </section>
          <Trace title="Speed over the last steps" help="From the physics, not the pictures" values={speeds} max={4} format={(v) => `${v.toFixed(1)} m/s`} />
          <p className="text-xs text-muted">Distance flown: {fmt(ph.distance_m, 1)} m · energy {fmt(ph.energy_wh, 3)} Wh</p>
        </>
      )}

      <section className="rounded-xl border border-line bg-surface p-4">
        <h2 className="flex items-center gap-2 font-semibold">
          <Scale className="h-4 w-4 text-accent" aria-hidden /> Calibration weight
        </h2>
        <p className="mt-1.5 text-sm leading-relaxed text-ink-2">
          After every flight Lucid compares how far the picture turned with how far the physics turned, and keeps a weight that
          makes the two agree. It gets more precise with every flight.
        </p>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
          <div className="rounded-lg bg-surface-2 p-2">
            <dt className="text-xs text-muted">Turn weight (1.00 = agree)</dt>
            <dd className="num text-lg font-semibold">{cal.k_yaw_saved !== undefined ? cal.k_yaw_saved.toFixed(2) : "1.00"}</dd>
          </div>
          <div className="rounded-lg bg-surface-2 p-2">
            <dt className="text-xs text-muted">Flights learned from</dt>
            <dd className="num text-lg font-semibold">{cal.flights_calibrated ?? 0}</dd>
          </div>
        </dl>
        {cal.k_yaw !== undefined && (
          <p className="mt-2 text-xs text-muted">
            Last flight measured {cal.k_yaw.toFixed(2)} (fit r² {cal.yaw_fit_r2?.toFixed(2) ?? "—"}
            {cal.speed_tracking_corr !== undefined ? `, picture speed follows physics speed r = ${cal.speed_tracking_corr.toFixed(2)}` : ""}).
          </p>
        )}
      </section>

      {flight?.report_id && !flying && (
        <Link
          href={`/report/${flight.report_id}`}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-accent-fill px-4 py-2.5 text-sm font-semibold text-white hover:opacity-90"
        >
          <FileText className="h-4 w-4" aria-hidden /> Open the flight report
        </Link>
      )}
    </div>
  );
}
