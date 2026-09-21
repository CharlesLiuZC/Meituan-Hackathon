"""Official-objective greedy solver (fallback submission artifact).

objective = total_score + 100 * missing_tasks, where total_score sums every
assigned candidate (multi-courier backups all count). Under this metric a
backup courier only pays off if it prevents a missing task. This solver:
  1. sorts candidates by score-per-task (bundle-aware) ascending;
  2. greedily picks non-conflicting candidates until all tasks are covered;
  3. tops up any uncovered tasks with their single cheapest candidate.
Deterministic, stdlib-only, completes in milliseconds.
"""
import sys

CONFIG = {"time_budget_ms": 9300.0}  # unused; kept for studio worker compatibility


def solve(input_text: str) -> list:
    lines = input_text.strip().splitlines()
    start = 1 if lines and lines[0].startswith("task_id_list") else 0
    cands = []
    all_tasks = set()
    for line in lines[start:]:
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        try:
            score = float(parts[2])
        except ValueError:
            continue
        tstr = parts[0].strip()
        cid = parts[1].strip()
        ts = frozenset(t for t in tstr.split(",") if t)
        if not ts:
            continue
        cands.append((score, tstr, cid, ts))
        all_tasks |= ts
    if not cands:
        return []

    cands.sort(key=lambda c: (c[0] / len(c[3]), c[0]))
    used_tasks, used_couriers, total = set(), set(), 0.0
    selected = []
    for score, tstr, cid, ts in cands:
        if ts & used_tasks or cid in used_couriers:
            continue
        selected.append((tstr, [cid]))
        used_tasks |= ts
        used_couriers.add(cid)
        total += score
        if used_tasks >= all_tasks:
            return selected

    # top up missing tasks with their cheapest conflict-free single candidates
    singles = {}
    for score, tstr, cid, ts in cands:
        if len(ts) != 1:
            continue
        t = next(iter(ts))
        if (t not in singles or score < singles[t][0]) and cid not in used_couriers:
            singles[t] = (score, tstr, cid)
    for t in sorted(all_tasks - used_tasks):
        if t in singles and singles[t][2] not in used_couriers:
            score, tstr, cid = singles[t]
            selected.append((tstr, [cid]))
            used_couriers.add(cid)
            used_tasks.add(t)
    return selected
