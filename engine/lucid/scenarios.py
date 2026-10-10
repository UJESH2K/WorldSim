"""Domain randomisation by prompt.

In a hand-built simulator, fog, night, smoke or a worker stepping into the aisle each cost
an asset, a shader or a scripted agent. In a world model each one is a sentence, and it can
be hot-swapped mid-episode with `set_prompt`. The mock world maps the same sentences onto
its own knobs, so a scenario means the same thing on both backends.
"""
import numpy as np

from .config import ASSETS
from .worlds.base import Scene

SEEDS = ASSETS / "seeds"

# LingBot World 2 prompt guide: first-person scenes must use its camera template verbatim, built
# around a foreground anchor, or the viewpoint drifts (our first closed-loop run sank to the
# ground). The height sentence is ours: a drone has to hold altitude.
CAMERA = ("Strict first-person view, the {anchor} holding steady at the centre of the frame as the "
          "viewpoint advances through the scene; look-input becomes the heading changing. "
          "The viewpoint holds a constant height about one metre above the ground with the horizon level.")

BASES = {
    "warehouse": dict(
        prompt=("A warehouse aisle between tall pallet racks stacked with cardboard boxes, concrete floor, "
                "overhead industrial lights, seen from a small inspection drone. "
                + CAMERA.format(anchor="far end of the aisle")),
        image="warehouse.jpg",
        params={"palette": "warehouse", "density": 7.0},
    ),
    "forest": dict(
        # Describes engine/assets/seeds/forest.jpg; LingBot drifts when prompt and image disagree.
        prompt=("The entrance of a sunlit woodland path, wooden posts and white signboards beside the path, "
                "tall tree trunks and green ferns, seen from a small drone. "
                + CAMERA.format(anchor="path ahead")),
        image="forest.jpg",
        params={"palette": "forest", "density": 6.0},
    ),
}

CONDITIONS = {
    "clear": ("", {}),
    "fog": (" Thick fog fills the air and visibility drops to a few metres.", {"fog": 0.12}),
    "night": (" It is night; the only light is the drone's own spotlight.", {"palette": "night"}),
}

# Contextual-entrance form from the prompt guide: preserve the scene, then add the hazard.
EVENTS = [
    "The scene remains unchanged while a worker suddenly steps into the path directly ahead.",
    "The scene remains unchanged while a stack of boxes falls into the path directly ahead.",
    "The scene remains unchanged while a forklift crosses the path directly ahead.",
]


def make_scene(base: str, condition: str = "clear", seed: int = 0, event_at: int | None = None,
               event: str | None = None) -> Scene:
    spec = BASES[base]
    extra, params = CONDITIONS[condition]
    events = []
    if event_at is not None:
        events.append({"at": event_at, "prompt": spec["prompt"] + extra + " " + (event or EVENTS[0])})
    image = SEEDS / spec["image"]
    return Scene(
        name=f"{base}-{condition}" + ("-event" if events else ""),
        prompt=spec["prompt"] + extra,
        seed_image=str(image) if image.exists() else None,
        seed=seed,
        params={**spec["params"], **params},
        events=events,
    )


def sample_scenes(n: int, seed: int, bases=("warehouse", "forest"), conditions=("clear", "fog", "night"),
                  event_rate: float = 0.5, max_chunks: int = 40) -> list[Scene]:
    rng = np.random.default_rng(seed)
    scenes = []
    for i in range(n):
        has_event = rng.random() < event_rate
        scenes.append(make_scene(
            base=str(rng.choice(bases)),
            condition=str(rng.choice(conditions)),
            seed=int(rng.integers(0, 1_000_000)),
            event_at=int(rng.integers(max_chunks // 4, max_chunks // 2)) if has_event else None,
            event=str(rng.choice(EVENTS)),
        ))
    return scenes
