import Link from "next/link";
import {
  ArrowRight,
  Bot,
  Camera,
  Eye,
  Gauge,
  Hammer,
  Keyboard,
  MessageSquareText,
  Radar,
  ShieldAlert,
  Sparkles,
  Wallet,
  Waves,
} from "lucide-react";
import showcase from "@/data/showcase.json";
import lab from "@/data/lab.json"; // exported from the Pilot Lab run and the world audits (engine/data)
import { FrameOverlay, Logo, VerdictBadge } from "@/components/common";
import { HeroReel } from "@/components/landing/HeroReel";
import type { Hazard, Verdict } from "@/lib/model";

const NAV = [
  { href: "#problem", label: "The problem" },
  { href: "#how", label: "How it works" },
  { href: "#proof", label: "See it work" },
  { href: "#referee", label: "The referee" },
  { href: "#learning", label: "Learning" },
  { href: "#physics", label: "Physics" },
  { href: "#limits", label: "Honest limits" },
];

const PROBLEMS = [
  {
    icon: Wallet,
    title: "Real crashes are expensive",
    body: "A single crash can cost more than the drone. Testing inside a working warehouse means stopping real work and risking real people.",
  },
  {
    icon: Hammer,
    title: "Simulators take months to build",
    body: "Classic simulators need every shelf, tree and light modelled by hand, and they still never look quite like the real place.",
  },
  {
    icon: Sparkles,
    title: "AI-generated worlds don't know physics",
    body: "A world model can paint a convincing scene, but it has no idea what a collision is. Someone has to watch for crashes.",
  },
];

const STEPS = [
  {
    icon: Camera,
    title: "Start from one photo",
    body: "Take a photo of the place. Lucid puts the drone in the picture: no 3D model, no map.",
    img: "/scenes/forest.jpg",
  },
  {
    icon: Waves,
    title: "The world builds itself",
    body: "Reactor's LingBot World 2 generates every next frame in real time as the drone moves. Nothing is pre-built.",
    img: "/showcase/hero.jpg",
  },
  {
    icon: Keyboard,
    title: "Fly it, or let the autopilot",
    body: "Steer with the keyboard or the on-screen buttons, or hand over to the autopilot, which makes two decisions every second.",
    img: "/showcase/clear-warehouse.jpg",
  },
  {
    icon: ShieldAlert,
    title: "A referee calls every crash",
    body: "An independent safety referee watches every frame and flags near misses, collisions and moments the world itself breaks.",
    img: "/showcase/ranger-at-drone.jpg",
  },
];

const SIGNALS = [
  {
    icon: Eye,
    title: "Spots people and vehicles",
    body: "An object detector boxes anyone in view and measures how far they are from the drone, including whether they are actually beside it or just closer to the camera.",
  },
  {
    icon: Radar,
    title: "Feels things getting closer",
    body: "Motion in the image tells it when a post, trunk or rack is swelling in front of the drone, even when there is no label for it.",
  },
  {
    icon: Bot,
    title: "Checks the drone still looks like the drone",
    body: "Generated worlds sometimes melt their subject. If the drone stops matching itself, the referee says the world broke.",
  },
  {
    icon: Gauge,
    title: "Checks the world obeys the controls",
    body: "If the drone is told to fly forward and the world keeps doing something else, those moments are flagged and never trusted.",
  },
];

const FACTS = [
  { value: "2", unit: "decisions / second", note: "the autopilot re-plans every half second" },
  { value: "≈1 s", unit: "command to effect", note: "measured on the live world model" },
  { value: "40 ms", unit: "to spot a person", note: "on a laptop CPU, no cloud needed" },
  { value: "$0.42", unit: "per minute of world", note: "practice mode is free" },
];

const LIMITS = [
  {
    q: "Does the generated world know real physics?",
    a: "The world model does not, so it is not in charge of physics. The drone's motion, speed, tilt and battery come from a MuJoCo rigid-body simulation. What the generated world cannot give is geometry, so collisions with things in the picture are still the referee's reading of the pixels.",
  },
  {
    q: "Will it catch every obstacle?",
    a: "Not yet. People and vehicles are caught reliably. Posts, trunks and racks are caught by motion alone, which is a weaker signal when viewed from behind the drone.",
  },
  {
    q: "Has it flown a real drone?",
    a: "Not yet. Everything you see happens inside the generated world; how well the tuned autopilot transfers to a real drone is still unmeasured.",
  },
  {
    q: "Does the pilot learn inside the photoreal AI world?",
    a: "No. It learns in the practice world, where obstacles have true positions and a crash is a fact, and where thousands of flights are free. Doing that on the AI world would cost hundreds of dollars per run. The AI world is where the learned pilot is tested, and the world audit says which of those moments can be trusted.",
  },
  {
    q: "Does re-anchoring stop the world model drifting?",
    a: "It pulls the world back to the last frame that still matched your photo, but the model can drift again. Every drift is logged, so you always know which part of a flight to trust.",
  },
  {
    q: "What does a flight cost?",
    a: "Practice mode is free and runs on your laptop. The photoreal world costs about $0.42 a minute, and every flight has a time cap you set before it starts.",
  },
  {
    q: "Is the local AI narrator deciding anything?",
    a: "No. It describes the scene in plain words for people watching. Its own safety opinions proved unreliable, so it never votes.",
  },
];

const LOOP = [
  { title: "Fly", body: "The pilot flies 48 fresh flights in parallel from camera pixels alone: colour view plus what changed since its last decision." },
  { title: "Find every mistake", body: "Every crash and every pass closer than 0.6 m, plus the six decisions that led into it." },
  { title: "Relabel with an expert", body: "A planner that knows where obstacles really are simulates each command 1.5 s ahead on the quadrotor's dynamics and names the safe one (DAgger)." },
  { title: "Reinforce", body: "Imitation on everything gathered so far, plus advantage-weighted regression: choices that beat the value network's expectation are strengthened." },
  { title: "Re-score, keep the best", body: "Each version is scored on held-out flights. The best weights are saved, and each original mistake is checked: fixed or not." },
];

const PIPELINE = [
  { title: "Physics", body: "MuJoCo integrates a 6-DoF quadrotor (1.0 kg, 350 mm, Phantom 2 class) at 400 Hz: thrust, rotor torque, motor lag, drag, gravity, ground contact, battery." },
  { title: "Flight controller", body: "A PX4-style cascade turns each command into motor speeds: velocity, then attitude and thrust, then a rate PID and the mixer. Its gains are the tunable weights." },
  { title: "Renderer", body: "The world model draws the motion the physics produced. Practice worlds move exactly by it; the AI world is steered to match it." },
  { title: "Calibration loop", body: "Every flight compares how far the picture moved with how far the physics moved, and updates a weight so the two agree better next time." },
  { title: "Flight report", body: "Each flight ends with requirements checked (collisions, separation, battery, tilt, world validity), metrics and what to change." },
];

const VALIDATION: [string, string, string][] = [
  ["Hover endurance", "25.1 min", "about 25 min"],
  ["Top speed (at the 35° tilt limit)", "14.9 m/s", "15 m/s"],
  ["0 to 90% of cruise speed", "1.0 s", "realistic inertia"],
  ["MuJoCo vs reference model, same 16.9 m manoeuvre", "0.5 cm apart", "independent check"],
  ["Calibration on a real photo (turn weight, 1.00 = exact)", "0.99, r² 0.999", "estimator validated"],
];

const GALLERY = ["ranger-at-drone", "ranger-between", "worker-aisle", "drums", "world-broke", "clear-warehouse"];

export default function Landing() {
  const gallery = GALLERY.map((id) => showcase.find((s) => s.id === id)!).filter(Boolean);
  return (
    <div className="min-h-screen overflow-x-clip">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-ink focus:px-3 focus:py-2 focus:text-bg">
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b border-line bg-bg/85 backdrop-blur">
        <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-6 px-4 sm:px-6" aria-label="Main">
          <Link href="/" aria-label="Lucid home">
            <Logo className="text-lg" />
          </Link>
          <ul className="hidden items-center gap-6 text-sm text-ink-2 md:flex">
            {NAV.map((n) => (
              <li key={n.href}>
                <a href={n.href} className="hover:text-ink">
                  {n.label}
                </a>
              </li>
            ))}
          </ul>
          <Link
            href="/sim"
            className="inline-flex items-center gap-2 rounded-lg bg-ink px-4 py-2 text-sm font-medium text-bg transition hover:opacity-90"
          >
            Open simulator <ArrowRight className="h-4 w-4" />
          </Link>
        </nav>
      </header>

      <main id="main">
        {/* Hero */}
        <section className="mx-auto grid max-w-6xl items-center gap-10 px-4 pb-16 pt-12 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:pt-20">
          <div className="rise">
            <p className="eyebrow">Drone flight simulator · Physical AI</p>
            <h1 className="mt-4 text-4xl font-semibold leading-[1.08] tracking-tight sm:text-5xl lg:text-[3.4rem]">
              Teach a drone to fly safely, before it ever leaves the ground.
            </h1>
            <p className="mt-5 max-w-xl text-lg leading-relaxed text-ink-2">
              Lucid turns one photo into a living, photoreal world. A drone practises inside it, a safety referee calls every
              near miss and crash, a vision pilot learns from each of its mistakes, and the world itself is audited for every
              moment it stops being your place.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href="/sim"
                className="inline-flex items-center gap-2 rounded-lg bg-accent-fill px-5 py-3 font-medium text-accent-ink shadow-sm transition hover:opacity-90"
              >
                Open the simulator <ArrowRight className="h-4 w-4" />
              </Link>
              <a href="#how" className="inline-flex items-center gap-2 rounded-lg border border-line-strong px-5 py-3 font-medium hover:bg-surface-2">
                See how it works
              </a>
            </div>
            <p className="mt-6 text-sm text-muted">Practice mode is free. No sign-up, nothing to install in the browser.</p>
          </div>
          <div className="rise" style={{ animationDelay: "80ms" }}>
            <HeroReel />
          </div>
        </section>

        <div className="border-y border-line bg-surface">
          <p className="mx-auto max-w-6xl px-4 py-4 text-center font-mono text-xs uppercase tracking-[0.14em] text-muted sm:px-6">
            Reactor LingBot World 2 · MuJoCo physics · PyTorch DAgger + RL pilot · ResNet-18 world audit · YOLO11 · Qwen2.5-VL local
          </p>
        </div>

        {/* Problem */}
        <section id="problem" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
          <p className="eyebrow">The problem</p>
          <h2 className="mt-3 max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">
            Robots learn by making mistakes. Real mistakes are expensive.
          </h2>
          <div className="mt-10 grid gap-5 md:grid-cols-3">
            {PROBLEMS.map((p) => (
              <article key={p.title} className="rounded-xl border border-line bg-surface p-6">
                <p.icon className="h-6 w-6 text-accent" aria-hidden />
                <h3 className="mt-4 text-lg font-semibold">{p.title}</h3>
                <p className="mt-2 leading-relaxed text-ink-2">{p.body}</p>
              </article>
            ))}
          </div>
        </section>

        {/* How it works */}
        <section id="how" className="scroll-mt-20 border-y border-line bg-surface">
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
            <p className="eyebrow">How it works</p>
            <h2 className="mt-3 max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">From one photo to a safe flight, in four steps.</h2>
            <ol className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
              {STEPS.map((s, i) => (
                <li key={s.title} className="flex flex-col overflow-hidden rounded-xl border border-line bg-bg">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={s.img} alt="" className="aspect-[16/10] w-full object-cover" loading="lazy" />
                  <div className="p-5">
                    <div className="flex items-center gap-2">
                      <span className="grid h-7 w-7 place-items-center rounded-full bg-ink font-mono text-xs font-semibold text-bg">{i + 1}</span>
                      <s.icon className="h-5 w-5 text-accent" aria-hidden />
                    </div>
                    <h3 className="mt-3 font-semibold">{s.title}</h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{s.body}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Proof */}
        <section id="proof" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
          <p className="eyebrow">See it work</p>
          <h2 className="mt-3 max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">Real flights. Real calls.</h2>
          <p className="mt-4 max-w-2xl text-ink-2">
            Every frame below was generated live by LingBot World 2 during our test flights. The boxes are the referee&apos;s own
            readings: the drone in its frame, and anything it decided was a risk.
          </p>
          <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {gallery.map((g) => (
              <figure key={g.id} className="overflow-hidden rounded-xl border border-line bg-surface">
                <div className="relative bg-[#0b0c0e]" style={{ aspectRatio: `${g.width} / ${g.height}` }}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={g.src} alt={g.caption} className="absolute inset-0 h-full w-full object-cover" loading="lazy" />
                  <FrameOverlay droneBox={g.droneBox} hazards={g.hazards as Hazard[]} verdict={g.verdict as Verdict} showLabels={false} />
                  <VerdictBadge verdict={g.verdict as Verdict} size="sm" className="absolute left-2 top-2" />
                </div>
                <figcaption className="p-4">
                  <p className="leading-snug">{g.caption}</p>
                  {g.reasons[0] && <p className="mt-1.5 text-sm text-muted">Referee: {g.reasons.join("; ")}</p>}
                  {"liveOnly" in g && <p className="mt-1 text-xs text-muted">Called live over several frames in a row.</p>}
                </figcaption>
              </figure>
            ))}
          </div>
        </section>

        {/* Referee */}
        <section id="referee" className="scroll-mt-20 border-y border-line bg-surface">
          <div className="mx-auto grid max-w-6xl gap-12 px-4 py-20 sm:px-6 lg:grid-cols-[1fr_1.2fr]">
            <div>
              <p className="eyebrow">The referee</p>
              <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">A generated world has no physics. So we watch every frame.</h2>
              <p className="mt-4 text-ink-2">
                The referee combines four simple checks into one call per step, from <em>clear</em> to <em>collision</em>. Each
                check can be tested on its own, which is why we trust it more than any single AI opinion.
              </p>
              <div className="mt-6 flex flex-wrap gap-2">
                {(["clear", "caution", "warning", "collision", "anomaly"] as Verdict[]).map((v) => (
                  <VerdictBadge key={v} verdict={v} size="sm" />
                ))}
              </div>
              <div className="mt-8 flex items-start gap-3 rounded-xl border border-line bg-bg p-4">
                <MessageSquareText className="mt-0.5 h-5 w-5 shrink-0 text-accent" aria-hidden />
                <p className="text-sm leading-relaxed text-ink-2">
                  A small AI model running on your own laptop also describes the scene in plain words for people watching. It
                  never votes: its safety opinions proved unreliable in our tests.
                </p>
              </div>
            </div>
            <ul className="grid gap-4 sm:grid-cols-2">
              {SIGNALS.map((s) => (
                <li key={s.title} className="rounded-xl border border-line bg-bg p-5">
                  <s.icon className="h-6 w-6 text-accent" aria-hidden />
                  <h3 className="mt-3 font-semibold">{s.title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{s.body}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Learning */}
        <section id="learning" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
          <p className="eyebrow">It learns from every mistake</p>
          <h2 className="mt-3 max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">
            Import a pilot. Watch it crash. Watch it stop crashing.
          </h2>
          <p className="mt-4 max-w-3xl text-ink-2">
            A stock pilot network that only ever saw sunny open fields is put where it has to work: warehouse aisles, night,
            clutter, people stepping into its path. Every crash and close call it makes becomes training data. Its weights are
            updated by imitation of a privileged expert and by reinforcement learning, and every version is scored on flights
            it never trains on.
          </p>
          <div className="mt-10 grid gap-6 lg:grid-cols-[1.1fr_1fr]">
            <div className="rounded-xl border border-line bg-surface p-6">
              <dl className="grid grid-cols-3 gap-4">
                {[
                  { k: "Crash rate", a: `${Math.round(lab.before.crash_rate * 100)}%`, b: `${Math.round(lab.after.crash_rate * 100)}%` },
                  { k: "Distance flown", a: `${lab.before.mean_distance_m.toFixed(1)} m`, b: `${lab.after.mean_distance_m.toFixed(1)} m` },
                  { k: "Mistakes fixed", a: `of ${lab.mistakes}`, b: String(lab.fixed) },
                ].map((m) => (
                  <div key={m.k}>
                    <dt className="text-sm text-ink-2">{m.k}</dt>
                    <dd className="num mt-1 whitespace-nowrap text-2xl font-semibold tracking-tight text-clear sm:text-3xl">{m.b}</dd>
                    <dd className="num text-sm text-muted">{m.k === "Mistakes fixed" ? m.a : `from ${m.a}`}</dd>
                  </div>
                ))}
              </dl>
              <svg viewBox="0 0 400 120" className="mt-6 h-32 w-full" role="img"
                aria-label={`Crash rate by version: ${lab.curve.map((c) => `${c.v} ${Math.round(c.crash * 100)}%`).join(", ")}`}>
                {[0, 0.5, 1].map((t) => <line key={t} x1="0" x2="400" y1={10 + t * 95} y2={10 + t * 95} stroke="var(--line)" />)}
                <polyline fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinejoin="round"
                  points={lab.curve.map((c, i) => `${(i / (lab.curve.length - 1)) * 390 + 5},${105 - c.crash * 95}`).join(" ")} />
                {lab.curve.map((c, i) => (
                  <circle key={c.v} cx={(i / (lab.curve.length - 1)) * 390 + 5} cy={105 - c.crash * 95} r={c.v === lab.best ? 5 : 3}
                    fill={c.v === lab.best ? "var(--clear)" : "var(--accent)"} />
                ))}
              </svg>
              <p className="mt-2 text-xs text-muted">
                Crash rate on {lab.bench} held-out flights after each iteration (lower is better); green: {lab.best}, the version kept.
              </p>
              <p className="mt-4 rounded-lg bg-surface-2 px-3 py-2.5 text-sm text-ink-2">
                Then flown in the simulator&apos;s own loop on {lab.sim_compare.flights} identical flights: the hand-tuned autopilot
                crashed on <b className="num text-ink">{Math.round(lab.sim_compare.reflex.crash * 100)}%</b>, the learned pilot on{" "}
                <b className="num text-clear">{Math.round(lab.sim_compare.learned.crash * 100)}%</b>, flying{" "}
                {lab.sim_compare.learned.distance} m instead of {lab.sim_compare.reflex.distance} m.
              </p>
              <Link href="/lab" className="mt-5 inline-flex items-center gap-2 text-sm font-medium text-accent hover:underline">
                Open the Pilot Lab and watch the before and after <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
            <ol className="grid gap-3">
              {LOOP.map((step, i) => (
                <li key={step.title} className="flex gap-4 rounded-xl border border-line bg-surface p-4">
                  <span className="font-mono text-xs text-muted">{String(i + 1).padStart(2, "0")}</span>
                  <div>
                    <h3 className="font-semibold">{step.title}</h3>
                    <p className="mt-1 text-sm leading-relaxed text-ink-2">{step.body}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* World audit */}
        <section id="audit" className="scroll-mt-20 border-y border-line bg-surface">
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
            <p className="eyebrow">Catching the world model&apos;s own mistakes</p>
            <h2 className="mt-3 max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">
              When the generated world drifts away from your photo, we see it, log it, and pull it back.
            </h2>
            <p className="mt-4 max-w-3xl text-ink-2">
              On long flights a world model can turn your room into a different room, balloon the drone, shift the light or
              invent obstacles. A pretrained vision network compares every moment with your photo. Each failure is logged with
              its frame, and during a flight the world is restarted from the last frame that still passed every check.
            </p>
            <div className="mt-10 grid gap-4 md:grid-cols-3">
              {[
                { img: "/showcase/audit-office-start.jpg", label: "0 s · your photo, trusted", ok: true },
                { img: "/showcase/audit-office-drift.jpg", label: "50 s · another room, blue light, drone ballooned", ok: false },
                { img: "/showcase/audit-warehouse-drone.jpg", label: "10 s · drone re-rendered at twice its size", ok: false },
              ].map((f) => (
                <figure key={f.img} className="overflow-hidden rounded-xl border border-line bg-bg">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={f.img} alt={f.label} className="aspect-video w-full object-cover" />
                  <figcaption className={`px-4 py-3 text-sm font-medium ${f.ok ? "text-clear" : "text-collision"}`}>{f.label}</figcaption>
                </figure>
              ))}
            </div>
            <div className="mt-6 grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3">
              {[
                { v: `${lab.audit.length}`, k: "recorded AI flights audited", n: `${lab.audit.reduce((a, b) => a + b.chunks, 0)} moments checked` },
                { v: `${Math.round(Math.min(...lab.audit.map((a) => a.trusted)) * 100)}%`, k: "trusted, worst flight", n: "the office that turned into another room" },
                { v: "5", k: "kinds of failure caught", n: "drift, cut, colour, drone morph, pop-in" },
              ].map((s) => (
                <div key={s.k} className="bg-bg p-5">
                  <div className="num text-3xl font-semibold tracking-tight">{s.v}</div>
                  <div className="mt-1 text-sm text-ink-2">{s.k}</div>
                  <div className="text-xs text-muted">{s.n}</div>
                </div>
              ))}
            </div>
            <Link href="/audit" className="mt-6 inline-flex items-center gap-2 text-sm font-medium text-accent hover:underline">
              See every instance in the world audit <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </section>

        {/* Physics */}
        <section id="physics" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
          <p className="eyebrow">Real physics underneath</p>
          <h2 className="mt-3 max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">
            The world model draws the flight. A physics engine decides it.
          </h2>
          <p className="mt-4 max-w-3xl text-ink-2">
            A generated world has no mass, inertia or motors, so Lucid splits the job the way industry digital twins do: a
            rigid-body simulation is the source of truth for the drone, and the world model only renders what the physics says
            happened.
          </p>
          <ol className="mt-10 grid gap-4 md:grid-cols-5">
            {PIPELINE.map((step, i) => (
              <li key={step.title} className="rounded-xl border border-line bg-surface p-5">
                <span className="font-mono text-xs text-muted">{String(i + 1).padStart(2, "0")}</span>
                <h3 className="mt-2 font-semibold">{step.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{step.body}</p>
              </li>
            ))}
          </ol>
          <div className="mt-10 overflow-x-auto rounded-xl border border-line bg-surface">
            <table className="w-full text-left text-sm">
              <caption className="px-5 pt-4 text-left font-semibold">Validated against the real drone&apos;s spec sheet</caption>
              <thead className="text-muted">
                <tr className="border-b border-line">
                  <th className="px-5 py-2 font-normal">Check</th>
                  <th className="px-5 font-normal">Simulated</th>
                  <th className="px-5 font-normal">Real Phantom 2 spec</th>
                </tr>
              </thead>
              <tbody className="num">
                {VALIDATION.map((v) => (
                  <tr key={v[0]} className="border-b border-line last:border-0">
                    <td className="px-5 py-2.5">{v[0]}</td>
                    <td className="px-5 font-semibold">{v[1]}</td>
                    <td className="px-5 text-ink-2">{v[2]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Facts */}
        <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <p className="eyebrow">Measured, not promised</p>
          <dl className="mt-8 grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
            {FACTS.map((f) => (
              <div key={f.unit} className="bg-surface p-6">
                <dt className="text-sm text-ink-2">{f.unit}</dt>
                <dd className="mt-2 text-4xl font-semibold tracking-tight">{f.value}</dd>
                <dd className="mt-2 text-sm text-muted">{f.note}</dd>
              </div>
            ))}
          </dl>
        </section>

        {/* Limits */}
        <section id="limits" className="scroll-mt-20 border-t border-line bg-surface">
          <div className="mx-auto grid max-w-6xl gap-10 px-4 py-20 sm:px-6 lg:grid-cols-[1fr_1.4fr]">
            <div>
              <p className="eyebrow">Honest limits</p>
              <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">Said before anyone has to ask.</h2>
            </div>
            <div className="divide-y divide-line rounded-xl border border-line bg-bg">
              {LIMITS.map((l) => (
                <details key={l.q} className="group p-5 [&_summary::-webkit-details-marker]:hidden">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium">
                    {l.q}
                    <span className="text-xl leading-none text-muted transition group-open:rotate-45" aria-hidden>
                      +
                    </span>
                  </summary>
                  <p className="mt-3 leading-relaxed text-ink-2">{l.a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <div className="flex flex-col items-start justify-between gap-6 rounded-2xl bg-[#0b0c0e] p-8 text-white sm:p-12 md:flex-row md:items-center">
            <div>
              <h2 className="text-3xl font-semibold tracking-tight">Take it for a flight.</h2>
              <p className="mt-2 max-w-xl text-white/70">Start in the free practice world, then switch to the photoreal one when you are ready.</p>
            </div>
            <Link href="/sim" className="inline-flex items-center gap-2 rounded-lg bg-white px-5 py-3 font-medium text-[#0b0c0e] hover:opacity-90">
              Open the simulator <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-8 text-sm text-muted sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <Logo className="text-ink" />
          <p>Built for the Awign Hackathon: Physical AI, Bengaluru 2026.</p>
          <p>
            Photos: Wikimedia Commons (CC BY-SA 4.0), rawpixel (CC0), Flickr (CC BY 2.0).
          </p>
        </div>
      </footer>
    </div>
  );
}
