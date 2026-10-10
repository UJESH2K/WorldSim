"use client";

import { useEffect, useRef, useState } from "react";
import { ImagePlus, Loader2, Plane, Trash2, Upload, X } from "lucide-react";
import type { Catalog } from "@/lib/model";

type Created = { key: string; title: string; description: string; described_by: string };

/** Shrink to at most 1920 px wide in the browser so uploads stay small and fast. */
async function toJpegBase64(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 1920 / bitmap.width);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.9);
}

export function PlaceDialog({
  catalog,
  busy,
  onClose,
  onCreated,
  onDeleted,
}: {
  catalog: Catalog | null;
  busy: boolean;
  onClose: () => void;
  onCreated: (key: string) => void;
  onDeleted: (key: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<Created | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const saved = (catalog?.worlds ?? []).filter((w) => w.custom);

  useEffect(() => closeBtn.current?.focus(), []);
  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    const t = setTimeout(() => setPreview(url), 0);
    return () => {
      clearTimeout(t);
      URL.revokeObjectURL(url);
    };
  }, [file]);

  const pick = (f: File | undefined) => {
    if (!f) return;
    if (!f.type.startsWith("image/")) return setError("Please choose a photo (JPG or PNG).");
    setError("");
    setCreated(null);
    setFile(f);
  };

  const create = async () => {
    if (!file) return;
    setSaving(true);
    setError("");
    try {
      const image_b64 = await toJpegBase64(file);
      const r = await fetch("/engine/places", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ image_b64, title, description }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Could not create the world.");
      setCreated(body);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the world.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (key: string) => {
    const r = await fetch(`/engine/places/${key}`, { method: "DELETE" });
    if (r.ok) onDeleted(key);
    else setError((await r.json().catch(() => ({}))).detail ?? "Could not delete that place.");
  };

  return (
    <div className="fixed inset-0 z-[60] grid place-items-center overflow-y-auto bg-black/60 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="place-title"
        className="rise w-full max-w-2xl rounded-2xl border border-line bg-surface p-5 text-ink shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="place-title" className="text-lg font-semibold">
              Fly in your own place
            </h2>
            <p className="mt-1 text-sm text-muted">
              Upload a photo of the venue, a room or a warehouse. We place the drone in it and the world model builds the rest
              as it flies.
            </p>
          </div>
          <button ref={closeBtn} onClick={onClose} aria-label="Close" className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </div>

        {created ? (
          <div className="mt-5">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`/engine/places/${created.key}/thumb.jpg`} alt={`${created.title} with the drone placed in it`} className="w-full rounded-xl border border-line" />
            <p className="mt-3 font-semibold">{created.title} is ready.</p>
            <p className="mt-1 text-sm text-ink-2">
              The world model will treat it as: <em>{created.description}</em>
              {created.described_by === "default" && (
                <span className="mt-1 block text-collision">
                  No description was given and the local AI is not running, so it is described generically. For best
                  results, add the place again with a short description.
                </span>
              )}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                onClick={() => onCreated(created.key)}
                className="inline-flex items-center gap-2 rounded-lg bg-accent-fill px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
              >
                <Plane className="h-4 w-4" /> Fly here
              </button>
              <button
                onClick={() => {
                  setCreated(null);
                  setFile(null);
                  setPreview(null);
                  setTitle("");
                  setDescription("");
                }}
                className="rounded-lg border border-line-strong px-4 py-2 text-sm hover:bg-surface-2"
              >
                Add another
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-5 grid gap-5 md:grid-cols-[1.1fr_1fr]">
            <div>
              <button
                type="button"
                onClick={() => input.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragging(false);
                  pick(e.dataTransfer.files?.[0]);
                }}
                className={`relative grid aspect-[1664/960] w-full place-items-center overflow-hidden rounded-xl border-2 border-dashed text-center transition ${
                  dragging ? "border-accent bg-accent-soft" : "border-line-strong hover:border-accent"
                }`}
                aria-label="Choose a photo"
              >
                {preview ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={preview} alt="Your photo, cropped to the world's frame" className="absolute inset-0 h-full w-full object-cover" />
                ) : (
                  <span className="px-4">
                    <ImagePlus className="mx-auto h-8 w-8 text-accent" aria-hidden />
                    <span className="mt-2 block font-medium">Drop a photo here or click to choose</span>
                    <span className="mt-1 block text-xs text-muted">On a phone you can take one with the camera</span>
                  </span>
                )}
              </button>
              <input ref={input} type="file" accept="image/*" className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
              {preview && <p className="mt-2 text-xs text-muted">The preview shows how it will be cropped (16:9). The drone goes in the centre.</p>}
              <ul className="mt-3 space-y-1 text-xs text-muted">
                <li>• Landscape, taken at chest height, looking along an open path or aisle</li>
                <li>• Good, even light; avoid people standing in the middle</li>
                <li>• Leave the centre clear: that is where the drone appears</li>
              </ul>
            </div>

            <div className="flex flex-col gap-3">
              <label className="text-sm">
                <span className="text-ink-2">Name</span>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  maxLength={40}
                  placeholder="Venue hall"
                  className="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2 outline-none focus:border-accent"
                />
              </label>
              <label className="text-sm">
                <span className="text-ink-2">What is in the photo?</span>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  maxLength={240}
                  rows={4}
                  placeholder="a conference hall with rows of chairs, a stage and big windows"
                  className="mt-1 w-full resize-none rounded-lg border border-line bg-bg px-3 py-2 outline-none focus:border-accent"
                />
                <span className="mt-1 block text-xs text-muted">
                  The world model keeps the world true to this, so describe what you see. Left empty, a local AI describes it
                  (needs Ollama running).
                </span>
              </label>
              {error && (
                <p className="text-sm text-collision" role="alert">
                  {error}
                </p>
              )}
              <button
                onClick={create}
                disabled={!file || saving}
                className="mt-auto inline-flex items-center justify-center gap-2 rounded-lg bg-accent-fill px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-40"
              >
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                {saving ? "Building your world…" : "Create world"}
              </button>
            </div>
          </div>
        )}

        {saved.length > 0 && (
          <div className="mt-6 border-t border-line pt-4">
            <h3 className="text-sm font-semibold">Your saved places</h3>
            <ul className="mt-2 grid gap-2 sm:grid-cols-2">
              {saved.map((w) => (
                <li key={w.key} className="flex items-center gap-3 rounded-lg border border-line p-2">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={w.thumb} alt="" className="h-10 w-16 rounded object-cover" />
                  <span className="min-w-0 flex-1 truncate text-sm">{w.title}</span>
                  <button
                    onClick={() => onCreated(w.key)}
                    className="rounded-md px-2 py-1 text-xs text-accent hover:bg-accent-soft"
                  >
                    Select
                  </button>
                  <button
                    onClick={() => remove(w.key)}
                    disabled={busy}
                    aria-label={`Delete ${w.title}`}
                    className="grid h-7 w-7 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-collision disabled:opacity-40"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
