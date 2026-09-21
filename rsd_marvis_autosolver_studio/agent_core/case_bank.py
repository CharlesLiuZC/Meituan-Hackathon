"""Deterministic, scene-TRUE case bank generated from the official anchor.

Why not tools/generate_midtrain_cases.py: it samples rows but never changes the
task set, so its "medium"/"high_noise" cases still have ~40 tasks and the
solver's configure_runtime() routes them to the large_normal branch. Training on
mislabeled scenes gives the optimizer no signal for the branch it thinks it is
tuning. Here every scene is constructed to actually satisfy the runtime
detection conditions in submission/solver.py:

  medium          -> task_count == 30, normal willingness, courier_ratio > 1
  high_noise      -> task_count == 30, avg_willingness >= 0.42, std >= 0.21
  large           -> task_count >= 35, normal
  low_willingness -> avg_willingness < 0.18
  scarce_couriers -> courier_ratio <= special_courier_ratio_threshold (1.0)

Splits: train/ (screening), holdout/ (per-scene validation), protected/
(tiny/small/scarce no-regression proxies).
"""
from __future__ import annotations

import json
import random
import zlib
from pathlib import Path

ANCHOR = Path("data/official/large_seed301.txt")
BANK = Path("data/case_bank")
HEADER = "task_id_list\tcourier_id\ttotal_score\twillingness\n"

SCENES = ["medium", "high_noise", "large", "low_willingness", "scarce_couriers"]
PROTECTED = {"tiny": 6, "small": 15, "scarce_couriers": 40}


def parse_anchor(path: Path) -> list[tuple[str, str, float, float]]:
    rows = []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    start = 1 if lines and lines[0].startswith("task_id_list") else 0
    for line in lines[start:]:
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        try:
            rows.append((parts[0].strip(), parts[1].strip(), float(parts[2]), float(parts[3])))
        except ValueError:
            continue
    return rows


def _build_case(rows, scene: str, rng: random.Random, task_k: int) -> list[tuple[str, str, float, float]]:
    all_tasks = sorted({t for task_str, *_ in rows for t in task_str.split(",") if t})
    all_couriers = sorted({c for _, c, _, _ in rows})
    task_subset = set(rng.sample(all_tasks, min(task_k, len(all_tasks))))

    if scene == "scarce_couriers":
        courier_k = max(1, int(task_k * float(rng.uniform(0.85, 1.0))))
        courier_subset = set(rng.sample(all_couriers, min(courier_k, len(all_couriers))))
    else:
        courier_subset = set(all_couriers)

    kept = []
    for task_str, courier, score, w in rows:
        tasks = task_str.split(",")
        if not set(tasks) <= task_subset or courier not in courier_subset:
            continue
        if scene == "high_noise":
            score = score * rng.uniform(0.75, 1.25)
            w = min(0.98, max(0.01, w * 1.55 + rng.uniform(-0.10, 0.10)))
        elif scene == "low_willingness":
            w = min(0.35, max(0.01, w * 0.45 + rng.uniform(0.0, 0.03)))
        elif scene == "scarce_couriers":
            if rng.random() < 0.18:
                continue
            score = score * rng.uniform(0.92, 1.08)
            w = min(0.98, max(0.01, w + rng.uniform(-0.03, 0.03)))
        else:  # medium / large: mild jitter
            score = score * rng.uniform(0.92, 1.08)
            w = min(0.98, max(0.01, w + rng.uniform(-0.03, 0.03)))
        kept.append((task_str, courier, round(max(1.0, score), 3), round(w, 4)))
    return kept


def _write_case(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(HEADER)
        for task_str, courier, score, w in rows:
            f.write(f"{task_str}\t{courier}\t{score}\t{w}\n")


def case_features(rows) -> dict:
    tasks = {t for task_str, *_ in rows for t in task_str.split(",") if t}
    couriers = {c for _, c, _, _ in rows}
    ws = [w for _, _, _, w in rows]
    avg_w = sum(ws) / max(1, len(ws))
    std_w = (sum((x - avg_w) ** 2 for x in ws) / max(1, len(ws))) ** 0.5
    return {
        "rows": len(rows), "tasks": len(tasks), "couriers": len(couriers),
        "courier_ratio": round(len(couriers) / max(1, len(tasks)), 3),
        "avg_willingness": round(avg_w, 4), "willingness_std": round(std_w, 4),
    }


def expected_case_type(features: dict) -> str:
    if features["avg_willingness"] < 0.18:
        return "low_willingness"
    if features["courier_ratio"] <= 1.0:
        return "scarce_couriers"
    if features["tasks"] >= 35:
        return "large"
    if features["tasks"] == 30 and features["avg_willingness"] >= 0.42 and features["willingness_std"] >= 0.21:
        return "high_noise"
    if features["tasks"] == 30:
        return "medium"
    return "medium"


def ensure_case_bank(root: Path, train_per_scene: int = 2, holdout_per_scene: int = 1,
                     force: bool = False) -> dict:
    root = Path(root)
    anchor_path = root / ANCHOR
    manifest_path = root / BANK / "manifest.json"
    params = {"train_per_scene": train_per_scene, "holdout_per_scene": holdout_per_scene,
              "source": ANCHOR.as_posix(), "version": 2}
    if not force and manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            if old.get("params") == params:
                return old
        except Exception:
            pass

    rows = parse_anchor(anchor_path)
    if not rows:
        raise FileNotFoundError(f"anchor case missing or empty: {anchor_path}")
    manifest = {"params": params, "anchor": ANCHOR.as_posix(), "cases": []}

    def gen(split: str, scene: str, index: int, task_k: int) -> dict:
        # Deterministic per (split, scene, index) across processes (crc32, not
        # salted hash); resample seed until the case routes to the intended branch.
        case_rows, feats = [], {}
        for attempt in range(8):
            rng = random.Random(zlib.crc32(f"{split}|{scene}|{index}|{attempt}".encode()))
            case_rows = _build_case(rows, scene, rng, task_k)
            feats = case_features(case_rows)
            if expected_case_type(feats) == scene and feats["tasks"] == task_k:
                break
        else:
            feats = case_features(case_rows)  # best effort; trainer logs the mismatch
        rel = BANK.joinpath(split, scene, f"case_{index:03d}.txt").as_posix()
        _write_case(root / rel, case_rows)
        entry = {"path": rel, "split": split, "scene": scene, "features": feats,
                 "expected_case_type": expected_case_type(feats)}
        manifest["cases"].append(entry)
        return entry

    for scene, task_k in (("medium", 30), ("high_noise", 30), ("large", 40),
                          ("low_willingness", 40), ("scarce_couriers", 40)):
        for i in range(train_per_scene):
            gen("train", scene, i, task_k)
        for i in range(holdout_per_scene):
            gen("holdout", scene, i, task_k)
    for name, task_k in PROTECTED.items():
        gen("protected", name, 0, task_k)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def cases_of(manifest: dict, split: str, scene: str | None = None) -> list[str]:
    return [c["path"] for c in manifest.get("cases", [])
            if c["split"] == split and (scene is None or c["scene"] == scene)]
