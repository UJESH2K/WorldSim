"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft, CircleCheck, CircleX } from "lucide-react";
import { Logo } from "@/components/common";
import { WORLD_LABEL, type ReportSummary } from "@/lib/model";

export default function ReportsPage() {
  const [rows, setRows] = useState<ReportSummary[] | null>(null);
  useEffect(() => {
    fetch("/engine/reports")
      .then((r) => r.json())
      .then(setRows)
      .catch(() => setRows([]));
  }, []);
  return (
    <div className="min-h-screen bg-bg">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
          <Link href="/sim" className="inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-ink">
            <ArrowLeft className="h-4 w-4" /> Simulator
          </Link>
          <Logo className="text-ink" />
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8">
        <h1 className="text-3xl font-semibold tracking-tight">Flight reports</h1>
        <p className="mt-1 text-ink-2">Every flight produces one: physics, the referee&apos;s calls, requirements and what to change.</p>
        {rows === null && <p className="mt-6 text-muted">Loading…</p>}
        {rows?.length === 0 && <p className="mt-6 text-muted">No flights yet. Fly one in the simulator.</p>}
        {rows && rows.length > 0 && (
          <table className="mt-6 w-full text-left text-sm">
            <thead className="text-muted">
              <tr className="border-b border-line">
                <th className="py-2 font-normal">Verdict</th>
                <th className="font-normal">Place</th>
                <th className="font-normal">World</th>
                <th className="text-right font-normal">Distance</th>
                <th className="text-right font-normal">Collisions</th>
                <th className="text-right font-normal">When</th>
              </tr>
            </thead>
            <tbody className="num">
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-line hover:bg-surface">
                  <td className="py-2.5">
                    <Link href={`/report/${r.id}`} className="inline-flex items-center gap-1.5 font-semibold hover:underline">
                      {r.verdict === "PASS" ? <CircleCheck className="h-4 w-4 text-clear" aria-hidden /> : <CircleX className="h-4 w-4 text-collision" aria-hidden />}
                      {r.verdict}
                    </Link>
                  </td>
                  <td>{r.scene}</td>
                  <td className="text-ink-2">{WORLD_LABEL[r.world] ?? r.world}</td>
                  <td className="text-right">{r.distance_m} m</td>
                  <td className="text-right">{r.collisions}</td>
                  <td className="text-right text-ink-2">{r.at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </main>
    </div>
  );
}
