"""Pilot Lab: import a pilot model, find its mistakes, and improve its weights from them.

    benchmark  fixed, seeded scenarios in the practice world (MuJoCo-class physics + ground truth)
    expert     privileged planner that sees the true obstacles (learning-by-cheating teacher)
    pilot      vision policy: two camera frames -> flight command (+ value head for RL)
    train      recursive loop: roll out -> mistakes -> expert relabel + RL advantage -> update -> re-score
"""
