# LUCID — a drone that flies inside a world generated as it flies

Awign Hackathon: Physical AI · Bengaluru · Oct 10–11, 2026

A third-person drone, pinned to the centre of the frame, flying through a photoreal world that
Reactor's **LingBot World 2** generates around it in real time from a single photo. Fly it with
WASD, or leave it on autopilot and it makes a decision every half-second. A **Sentinel** calls
every crash, near miss and broken world, and an **auto-tuner** uses those calls to tune the
autopilot against the generated world before it ever flies a real one. A **Pilot Lab** takes a
pilot network's weights and improves them from every mistake it makes (DAgger + reinforcement
learning, before/after on held-out flights), and a **world audit** catches every moment the
generated world stops being your place, and pulls it back.

## The website

| Page | What it is for |
|---|---|
| `/` landing | explains the problem in plain words (why robots need safe practice, why simulators are slow, why generated worlds need a referee), how Lucid works in four steps, real LingBot frames with the referee's own calls drawn on them, measured numbers, and honest limits |
| `/sim` simulator | the product: pick a world (free practice / photoreal) and a place, set a time cap, press Fly |
| `/lab` Pilot Lab | import a pilot (.pt), run the improvement loop live, learning curves, side-by-side before/after replays, every mistake fixed or not |
| `/audit` World audit | every recorded LingBot flight: similarity to the photo per chunk, each failure with its frame |
| `/reports` | one report per flight (physics, requirements, world audit) |

Simulator UX:
- viewport toolbar: zoom in/out (or mouse wheel), drag to pan, fit, overlay on/off, save a snapshot, full screen
- fly with WASD and the arrow keys, or the on-screen press-and-hold pad (mouse or touch); Space toggles the autopilot
- live safety call on the video (icon + label + reason), toasts for collisions and broken worlds
- tabs: **Safety** (current call in plain words, three live measures with hover readouts, narrator), **Calls** (every warning with its frame), **World** (live world audit on LingBot), **Physics**, **Lab** (auto-tune, Pilot Lab)
- one bar per decision on the timeline: height = severity, colour = verdict, hover for details
- first-visit guided tour (compass icon to replay it), keyboard shortcuts on `?`
- phone layout: single column, sideways-scrolling setup bar

Design notes: status colours validated with the dataviz skill's palette checker (colour-blind
separation, normal-vision floor, contrast) and never used without an icon and a label; all text
pairings meet WCAG AA (4.5:1); reduced-motion respected; keyboard focus visible everywhere.

## Physics: the world model draws, MuJoCo decides

| Layer | What it is |
|---|---|
| Physics | MuJoCo 3.12 (built-in Newton-Euler model as fallback, `LUCID_PHYSICS=builtin`): 6-DoF quadrotor, Phantom 2 class (1.0 kg, 350 mm, 57.7 Wh), 400 Hz RK4, motor lag, rotor thrust and yaw torque, quadratic drag, ground contact, momentum-theory battery |
| Controller | PX4-style cascade: velocity P -> acceleration -> attitude + thrust -> rate PID -> mixer (gains in `lucid/control.py`) |
| Renderer | mock and photo worlds are moved exactly by the physics; LingBot is driven to match it (turn speed from the physics yaw rate / learned weight) |
| Calibration loop | each flight compares rendered motion (optical flow) with physical motion and updates a saved weight (`data/calibration.json`); used on the next flight |
| Flight report | every flight: requirements (no collision, >= 0.5 m separation, >= 20% battery, < 5% world anomalies, tilt envelope), metrics, recommendations; `/reports` in the web app |

Validation (`python scripts/physics_check.py`): hover endurance 25.1 min (spec ~25), top speed
14.9 m/s at the 35 deg tilt limit (spec 15), 90% of cruise speed in 1.0 s, MuJoCo vs reference
model 0.5 cm apart over a 16.9 m manoeuvre. Calibration on a real photo recovers turn weight
0.993 (r^2 0.999); on the synthetic mock it learns ~0.85 (optical flow under-reads its textures),
which is exactly what the weight is for.

## Pilot Lab: recursive learning from mistakes (`/lab`)

A vision pilot (PyTorch CNN, 0.49 M weights: chase-camera colour view + brightness change since
the last decision -> one of 11 commands, plus a value head) is imported as **v0** and improved by
its own mistakes:

1. **Fly**: 48 training flights in parallel (12 CPU processes) in the practice world, which has
   true obstacle positions and the quadrotor physics, so crashes are facts.
2. **Find mistakes**: every crash and every pass closer than 0.6 m, plus the 6 decisions before it.
3. **Relabel (DAgger)**: a privileged planner simulates every command 1.5 s ahead on the drone's
   dynamics and names the safe one; steps before a mistake weigh 3x. Early iterations let the
   expert take some decisions (beta 0.5 -> 0) so a weak pilot still reaches the hard parts.
4. **Reinforce**: imitation on the aggregated data + advantage-weighted regression (Peng et al.
   2019) on the pilot's own decisions; a value head learns the return. Learning rate decays.
5. **Re-score** on 32 held-out flights it never trains on; keep the best; check each of v0's
   mistakes: fixed or not. Before/after replays of the same flights are recorded.

The imported **factory pilot** (`scripts/factory_pilot.py`) was trained by imitation on sunny,
sparse, static open fields only: 12% crashes there, 67% in the field (warehouse, night, clutter,
people stepping in). Measured (`lab-20261010-124141`, ~25 min on CPU): crash rate **62% -> 6%**,
distance 12.9 -> 18.4 m, **44 of 50** of v0's mistakes fixed. Later versions can swing (v8-v10
went back to 22-31% before the learning-rate decay), which is why the best version is kept.
A second run reached 22% at its best: with 32 benchmark flights, one crash is 3 points, so treat
single numbers as +-7 points. Independent check in the simulator's own flight loop
(`scripts/compare_brains.py`, MuJoCo twin + Sentinel, 12 identical seeded flights): hand-tuned
autopilot 83% crashes / 10.6 m, learned pilot v7 25% / 17.6 m. Pick it in `/sim` under
Autopilot: *Learned (Lab)*.

What made it learnable (measured, `scripts/lab_diag.py`): with 80x48 grayscale input the pilot
could not learn the expert even from 9,600 demonstrations (crash 83%); colour, contrast
normalisation and a 4x6 spatial grid brought plain imitation to 29%.

```bash
.venv/Scripts/python scripts/factory_pilot.py              # the stock v0 (1 min)
.venv/Scripts/python scripts/lab_run.py --iterations 10    # or the Run button on /lab
```

## World audit: every instance the world model went wrong (`/audit`)

LingBot drifts on long flights: the room turns into another room, the drone balloons or
stretches, the light goes blue, obstacles appear unasked. `lucid/audit.py` checks every chunk:

| Signal | How | Limit (calibrated on 7 recorded LingBot flights) |
|---|---|---|
| scene drift | ResNet-18 (ImageNet) embedding of the frame, drone masked, vs the seed photo | < 0.80 (kept places 0.86-0.92, drifted 0.67-0.79) |
| scene cut | same embedding vs the previous chunk | < 0.70 |
| colour shift | mean CIELAB colour vs the seed | > 20 delta E (kept places <= 14, the blue office 33) |
| drone morphed | embedding of crops around the drone at 5 sizes vs the seed's drone | < 0.78 (healthy 0.80-0.95, morphed 0.71-0.76) |
| pop-in | a person/vehicle >= 30% of frame height, mid-frame, absent 3 chunks before, still there after | requested events excused |

Two failing chunks make an event (with its frame); four in a row **re-anchor** the live world:
reset + the last trusted frame as the new reference image + the same prompt, in the same session
(`ReactorWorld.reanchor`), at most every 16 chunks. The audit runs off the control path (~130 ms
of CNN per chunk). Recorded flights: `python scripts/audit_bank.py` (free, offline). The office
flight is 19% trusted from 6 s on; the two long woodland flights 100%. Re-anchoring is exercised
end to end on a replayed flight; it has not yet run against the live API.

## How a crash is called (a world model has no physics)

| Signal | Catches | Notes |
|---|---|---|
| YOLO11n boxes + geometry vs the drone's box | people and vehicles touching / within half a drone-width / in the flight path | depth from the chase view: a person whose feet are well below the drone's ground line is *between the camera and the drone*, not touching it |
| optical-flow looming around the masked drone | unlabelled obstacles (posts, trunks, racks) | weak from behind the drone (AUC 0.65 on the mock's ground truth), so it only raises caution / warning |
| drone presence (masked template match vs the seed) | the world model dropping, morphing or zooming its subject | caught LingBot's warehouse drone growing to fill the frame |
| obedience (flow vs commanded motion) | the world ignoring the controls | 3 steps in a row |
| narrator (qwen2.5-vl via Ollama, local) | nothing: it describes, it never votes | its "looks safe" judgements proved unreliable |

## Layout

```
engine/lucid/
  worlds/reactor_world.py  LingBot World 2: budget-capped session, layered prompts, 24 fps display frames
  worlds/mock.py           free raycast world with a chase camera and ground truth (dev + calibration)
  prompts.py               the two worlds (woodland path, warehouse floor) and LingBot's layered prompts
  sentinel.py              Sentinel + Narrator
  flight.py                live flight loop, autopilot, auto-tune
  perception.py            DIS optical flow: ego-motion, looming, obedience (drone masked out)
  dagger.py, policy.py     first pilot training (superseded by lab/)
  lab/                     Pilot Lab: pilot.py (network), expert.py (privileged planner), env.py
                           (parallel training ground), train.py (DAgger + AWR loop), run.py, api.py
  audit.py                 world-model audit + re-anchoring decision
  budget.py                spend ledger + server-side session cap
  server.py                FastAPI: /flight /control /autopilot /event /autotune /train /state /stream.mjpg
engine/assets/seeds/       forest_drone.jpg, warehouse_drone.jpg (drone composited into real photos)
engine/scripts/            probe_tp.py (third-person gate), ui_smoke.py (pre-demo check)
web/                       Next.js dashboard
```

## Run

```bash
# 0. Ollama running with qwen2.5vl:3b pulled (optional; only the narrator needs it)
# 1. engine
cd engine
python -m venv --system-site-packages .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m uvicorn lucid.server:app --port 8765
# 2. dashboard
cd web && npm install && npm run dev      # http://localhost:3000 (landing) and /sim (simulator)
```

Keys live in `.env.local` at the repo root (gitignored). Develop on the **mock world** (free);
pick **LingBot World 2** for the real thing. Every LingBot run has a cap in seconds that the
dashboard prices before you start, and Reactor ends the session at the cap even if the engine
crashes.

Pre-demo check (headless browser, needs `pip install playwright`):

```bash
.venv/Scripts/python scripts/ui_smoke.py mock 0 forest           # free
.venv/Scripts/python scripts/ui_smoke.py mock-tune               # free
.venv/Scripts/python scripts/ui_smoke.py reactor 60 warehouse    # real credit, at most $0.42
```

## Measured (Oct 6)

**Third-person gate on LingBot** (`probe_tp.py`, $0.19): the drone stays centred while the world is
generated around it; forward obedience 0.92–0.99, back 0.86–0.98; the "worker steps in" event
renders a person beside the drone within ~3 chunks.

**Live flights through the dashboard** ($0.24 each, ~35 s, ~50 decisions):
- woodland: ranger steps in → Sentinel calls it, autopilot reacts; after the depth fix, the
  frames where the ranger stood between camera and drone read *caution*, not *collision*.
- warehouse: correctly called a worker in the aisle and the drone driven into the drums, then
  10 "world broke" calls when the drone grew to fill the frame. The autopilot had backed away,
  which in a chase view flies the drone into the camera; it now brakes instead.

**Local models on a 4 GB RTX 3050:** YOLO11n 33–45 ms/frame on CPU; qwen2.5-vl ~3–4 s per
narration (needs `num_ctx` 4096, or it intermittently emits junk); qwen3-vl ~30 s (thinks first).

**Earlier first-person work** (still in the repo): action obedience probe, DAgger learning
curve on the mock (student 33% crashes at round 2 vs teacher 25%), budget guards.

## Honest limits

- No physics: a "collision" is the Sentinel's reading of pixels, not a measured contact.
- Static obstacles are only caught by looming, which is weak from behind the drone.
- Third-person framing can break (the drone zooms or morphs); the audit flags it and re-anchors, which reduces drift but cannot stop the model from drifting again.
- The Pilot Lab trains in the practice world (ground truth, free); thousands of flights on LingBot would cost hundreds of dollars. Transfer of the learned pilot to LingBot and to real drones is unmeasured.
- Nothing has flown a real drone yet; the generated-world → real-world gap is unmeasured.
- ~2 decisions per second, ~1 s from command to effect.
- Prior art in the same city: DÉJÀ-VU (Inception Hackathon 2.0) plans with a world model and
  measures doubt. LUCID flies inside one and calls crashes in it. Cite it.

## Credits

Seed photos: woodland path (Wikimedia Commons, CC BY-SA 4.0), warehouse (rawpixel, CC0), drone
("Drone and Moon", Flickr, CC BY 2.0). See `engine/assets/seeds/CREDITS.md`.
