"""Exact mask-DP reference for small protected cases (tiny=6, small=15 tasks).

dp[mask] = minimal expected penalty of covering exactly the tasks in `mask`
with disjoint single-courier bundles, objective = the evaluator's penalty_score
(first_accept_score + 100*len(tasks)*reject_probability). Transitions pick the
cheapest candidate for each sub-mask.

Caveats (documented, honest):
  * courier-uniqueness across chosen bundles is relaxed in the DP -> the value
    is a LOWER BOUND; we then check whether the optimal bundle set uses distinct
    couriers. If it does, the bound is THE exact optimum and directly comparable.
  * the champion may legally emit multi-courier backups, which the DP cannot
    express; below-DP champion scores are possible. The reference is a yardstick,
    not a proof, in that case.

Usage: python -m agent_core.exact_reference [case_path] ...
"""
from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

from .evaluator import split_tasks


def exact_reference(case_path: str | Path) -> dict:
    lines = Path(case_path).read_text(encoding="utf-8", errors="ignore").splitlines()
    start = 1 if lines and lines[0].startswith("task_id_list") else 0
    tasks: list[str] = []
    best: dict[tuple[frozenset, str], tuple[float, str]] = {}
    for line in lines[start:]:
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        tset = frozenset(split_tasks(parts[0]))
        if not tset:
            continue
        try:
            score, w = float(parts[2]), max(0.0, min(1.0, float(parts[3])))
        except ValueError:
            continue
        for t in tset:
            if t not in tasks:
                tasks.append(t)
        cost = score * w + 100.0 * len(tset) * (1.0 - w)
        key = (tset, parts[1])
        if key not in best or cost < best[key][0]:
            best[key] = (cost, parts[1])
    n = len(tasks)
    idx = {t: i for i, t in enumerate(tasks)}
    by_mask: dict[int, tuple[float, str]] = {}
    for (tset, _courier), (cost, courier) in best.items():
        m = 0
        for t in tset:
            m |= 1 << idx[t]
        if m not in by_mask or cost < by_mask[m][0]:
            by_mask[m] = (cost, courier)

    full = (1 << n) - 1
    INF = float("inf")
    dp = [INF] * (1 << n)
    choice: dict[int, tuple[int, float, str]] = {}
    dp[0] = 0.0
    masks = sorted(by_mask)
    for mask in range(1, 1 << n):
        # force-cover the lowest set bit to avoid symmetric permutations
        low = mask & -mask
        rest = mask ^ low
        sub = rest
        while True:
            cand = sub | low
            if cand in by_mask and dp[rest] + by_mask[cand][0] < dp[mask]:
                dp[mask] = dp[rest] + by_mask[cand][0]
                choice[mask] = (rest, *by_mask[cand])
            if sub == 0:
                break
            sub = (sub - 1) & rest

    # reconstruct and verify courier uniqueness
    couriers, feasible, mask = [], True, full
    while mask:
        prev, _cost, courier = choice[mask]
        if courier in couriers:
            feasible = False
        couriers.append(courier)
        mask = prev
    return {
        "case": Path(case_path).name, "tasks": n,
        "exact_or_bound": dp[full] if dp[full] < INF else None,
        "courier_conflict_free": feasible,
        "certified_optimum": feasible and dp[full] < INF,
        "bundles": len(couriers),
    }


def main(argv: list[str]) -> None:
    for path in argv:
        print(exact_reference(path))


if __name__ == "__main__":
    main(sys.argv[1:])
