"""CONFIG mutation spaces per scene.

Only keys that actually influence a solve: submission/solver.py's
apply_runtime_overrides() re-overwrites a set of keys at solve time depending on
the detected case type, so mutating those keys is a no-op. The spaces below
avoid them. Bounds keep every proposal inside sane operating range; the worker
additionally rejects unknown/protected keys.
"""
from __future__ import annotations

import random

# key -> (low, high, is_int)
BOUNDS: dict[str, tuple[float, float, bool]] = {
    "auto_strategy_budget_ms": (120.0, 600.0, False),
    "local_search_budget_ms": (0.0, 4000.0, False),
    "normal_preview_backup_cap": (1, 6, True),
    "normal_preview_scan_per_primary": (6, 60, True),
    "normal_topology_top_k": (2, 16, True),
    "normal_topology_generated_limit": (4, 30, True),
    "pair_top_k": (8, 80, True),
    "triple_top_k": (6, 60, True),
    "try_triples": (False, True, "bool"),
    "max_exact_replace_tasks": (4, 14, True),
    "max_candidates_per_mask": (8, 60, True),
    "special_max_candidates_per_mask": (2, 12, True),
    "backup_time_budget_ms": (200.0, 5000.0, False),
    "multi_primary_time_budget_ms": (0.0, 4000.0, False),
    "safety_margin_ms": (100.0, 900.0, False),
    "min_backup_utility": (0.0, 0.6, False),
    "max_extra_couriers_per_bundle": (1, 10, True),
}

# Effective knobs per scene (post-apply_runtime_overrides).
SCENE_KEYS: dict[str, list[str]] = {
    "medium": [
        "auto_strategy_budget_ms", "local_search_budget_ms", "normal_preview_backup_cap",
        "normal_preview_scan_per_primary", "normal_topology_top_k",
        "normal_topology_generated_limit", "pair_top_k", "triple_top_k", "try_triples",
        "max_exact_replace_tasks", "max_candidates_per_mask",
    ],
    "high_noise": [
        "auto_strategy_budget_ms", "local_search_budget_ms", "pair_top_k", "triple_top_k",
        "try_triples", "max_exact_replace_tasks", "max_candidates_per_mask",
    ],
    "large": [
        "auto_strategy_budget_ms", "local_search_budget_ms", "normal_preview_backup_cap",
        "normal_preview_scan_per_primary", "normal_topology_top_k",
        "normal_topology_generated_limit", "pair_top_k", "triple_top_k", "try_triples",
        "max_exact_replace_tasks",
    ],
    "low_willingness": [
        "pair_top_k", "triple_top_k", "try_triples", "max_exact_replace_tasks",
        "max_candidates_per_mask", "safety_margin_ms",
    ],
    "scarce_couriers": [
        "pair_top_k", "triple_top_k", "max_exact_replace_tasks",
        "max_candidates_per_mask", "special_max_candidates_per_mask", "safety_margin_ms",
    ],
}


def clamp(key: str, value):
    lo, hi, is_int = BOUNDS[key]
    if is_int == "bool":
        return bool(value)
    value = max(lo, min(hi, float(value)))
    return int(round(value)) if is_int else round(value, 1)


def mutate(current_config: dict, scene: str, rng: random.Random, n_keys: int = 2,
           keys: list[str] | None = None) -> dict:
    """Deterministic-search proposal: jitter 1-2 effective keys (optionally
    restricted to `keys`, e.g. leverage-guided proposals)."""
    allowed = [k for k in SCENE_KEYS.get(scene, SCENE_KEYS["medium"]) if k in current_config]
    if keys:
        allowed = [k for k in keys if k in allowed]
    if not allowed:
        return {}
    overrides = {}
    for key in rng.sample(allowed, min(n_keys, len(allowed))):
        lo, hi, is_int = BOUNDS[key]
        if is_int == "bool":
            overrides[key] = bool(rng.getrandbits(1))
            continue
        base = float(current_config.get(key, (lo + hi) / 2))
        base = min(max(base, lo), hi)
        span = (hi - lo) or 1.0
        delta = rng.uniform(-0.18, 0.18) * span
        overrides[key] = clamp(key, base + delta)
    return overrides


def jitter_strategies(current_config: dict, rng: random.Random) -> dict:
    """Perturb one weight inside one of the ordering-strategy tuples."""
    strategies = current_config.get("strategies")
    if not isinstance(strategies, list) or not strategies:
        return {}
    new = [list(s) for s in strategies]
    si = rng.randrange(len(new))
    wi = rng.randrange(len(new[si]))
    old = float(new[si][wi])
    scale = rng.uniform(0.85, 1.18) if old > 1e-6 else rng.uniform(0.0, 0.05)
    new[si][wi] = round(old * scale, 4)
    return {"strategies": [tuple(s) for s in new]}


def validate_overrides(current_config: dict, scene: str, proposals: dict) -> tuple[dict, list[str]]:
    """Whitelist-gate any proposal (LLM or human): known key, right type, in bounds."""
    accepted, rejected = {}, []
    allowed = set(SCENE_KEYS.get(scene, [])) | {"strategies"}
    for key, value in (proposals or {}).items():
        if key not in current_config or key not in BOUNDS and key != "strategies":
            rejected.append(f"{key}: unknown")
            continue
        if key not in allowed:
            rejected.append(f"{key}: ineffective for scene {scene}")
            continue
        if key == "strategies":
            s = value
            base_width = len(current_config["strategies"][0])
            if (isinstance(s, list) and 2 <= len(s) <= 6
                    and all(isinstance(t, (list, tuple)) and len(t) == base_width
                            for t in s)
                    and all(isinstance(x, (int, float)) and -2.0 <= float(x) <= 2.0
                            for t in s for x in t)):
                accepted[key] = [tuple(float(x) for x in t) for t in s]
            else:
                rejected.append("strategies: shape mismatch")
            continue
        lo, hi, is_int = BOUNDS[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            rejected.append(f"{key}: not numeric")
            continue
        if not (lo - 1e-9 <= float(value) <= hi + 1e-9):
            rejected.append(f"{key}: out of bounds [{lo}, {hi}]")
            continue
        accepted[key] = clamp(key, value)
    return accepted, rejected
