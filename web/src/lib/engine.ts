"use client";

import { useCallback, useEffect, useState } from "react";
import type { Catalog, EngineState } from "./model";

export * from "./model";

export function useEngine(intervalMs = 400) {
  const [state, setState] = useState<EngineState | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState("");

  // Re-read the list of worlds (after adding or deleting a place).
  const refreshCatalog = useCallback(async () => {
    try {
      setCatalog(await (await fetch("/engine/catalog", { cache: "no-store" })).json());
    } catch {}
  }, []);

  useEffect(() => {
    let alive = true;
    const loadCatalog = () =>
      fetch("/engine/catalog")
        .then((r) => r.json())
        .then((c) => alive && setCatalog(c))
        .catch(() => {});
    loadCatalog();
    const tick = async () => {
      try {
        const r = await fetch("/engine/state", { cache: "no-store" });
        if (!r.ok) throw new Error(String(r.status));
        const s = (await r.json()) as EngineState;
        if (!alive) return;
        setState(s);
        setOffline((was) => {
          if (was) loadCatalog();
          return false;
        });
      } catch {
        if (alive) setOffline(true);
      }
    };
    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [intervalMs]);

  const post = useCallback(async (path: string, body?: unknown) => {
    try {
      const r = await fetch(`/engine/${path}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}));
        setError(typeof detail.detail === "string" ? detail.detail : `Request failed (${r.status})`);
        return false;
      }
      setError("");
      return true;
    } catch {
      setError("The engine is not reachable.");
      return false;
    }
  }, []);

  return { state, catalog, offline, error, setError, post, refreshCatalog };
}
