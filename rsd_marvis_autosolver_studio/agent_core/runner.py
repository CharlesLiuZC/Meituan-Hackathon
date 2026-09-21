"""Parent-side runner: execute the solver in a subprocess and score the result."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .evaluator import evaluate_output, is_better

ROOT = Path(__file__).resolve().parent.parent
SOLVER_PATH = ROOT / "submission" / "solver.py"
WORKER_PATH = Path(__file__).resolve().parent / "solver_worker.py"

DEFAULT_SCREEN_BUDGET_MS = 3000.0
DEFAULT_FULL_BUDGET_MS = 9300.0
TIMEOUT_MARGIN_MS = 6000.0


def run_solver(case_path: str | Path, overrides: dict | None = None,
               budget_ms: float = DEFAULT_FULL_BUDGET_MS,
               solver_path: str | Path | None = None) -> dict:
    """Run one solve in a fresh subprocess. Never raises on solver failure."""
    job = {
        "solver_path": str(solver_path or SOLVER_PATH),
        "case_path": str(case_path),
        "overrides": overrides or {},
        "time_budget_ms": float(budget_ms),
    }
    timeout_s = (budget_ms + TIMEOUT_MARGIN_MS) / 1000.0
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    tmp.write(json.dumps(job, ensure_ascii=False))
    tmp.close()
    try:
        proc = subprocess.run(
            [sys.executable, str(WORKER_PATH), tmp.name],
            capture_output=True, text=True, encoding="utf-8", timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "elapsed_ms": budget_ms + TIMEOUT_MARGIN_MS,
                "solution": None, "case_type": None, "skipped_overrides": []}
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or "worker crash").strip()[-500:],
                "elapsed_ms": -1, "solution": None, "case_type": None, "skipped_overrides": []}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"bad worker output: {exc}", "elapsed_ms": -1,
                "solution": None, "case_type": None, "skipped_overrides": []}


def evaluate_case(case_path: str | Path, overrides: dict | None = None,
                  budget_ms: float = DEFAULT_FULL_BUDGET_MS,
                  solver_path: str | Path | None = None) -> dict:
    """Run + score. Returns {metrics..., 'case_type', 'elapsed_ms', 'ok'}."""
    run = run_solver(case_path, overrides, budget_ms, solver_path)
    input_text = Path(case_path).read_text(encoding="utf-8", errors="ignore")
    if not run.get("ok"):
        return {"ok": False, "error": run.get("error", "unknown"),
                "case_path": str(case_path), "overrides": overrides or {},
                "budget_ms": budget_ms, "elapsed_ms": run.get("elapsed_ms", -1),
                "case_type": run.get("case_type")}
    metrics = evaluate_output(input_text, run.get("solution"))
    metrics.update({
        "ok": True, "case_path": str(case_path), "overrides": overrides or {},
        "budget_ms": budget_ms, "elapsed_ms": run.get("elapsed_ms", -1),
        "case_type": run.get("case_type"),
        "skipped_overrides": run.get("skipped_overrides", []),
    })
    return metrics


def better_by_penalty(new: dict, old: dict, epsilon: float = 1e-6) -> bool:
    """Strictly better for promotion: valid, full coverage kept, penalty down."""
    if not new.get("ok") or not new.get("valid"):
        return False
    if not old:
        return True
    if int(new.get("covered_tasks", 0)) < int(old.get("covered_tasks", 0)):
        return False
    return float(new.get("penalty_score", float("inf"))) < float(old.get("penalty_score", float("inf"))) - epsilon


def screen_average(case_paths: list[str], overrides: dict | None, budget_ms: float,
                   solver_path: str | Path | None = None) -> dict:
    """Average penalty over several cases; robust candidate screening signal.
    solver_path screens a code-variant solver (L4) instead of CONFIG overrides."""
    runs = [evaluate_case(p, overrides, budget_ms, solver_path=solver_path) for p in case_paths]
    good = [r for r in runs if r.get("ok") and r.get("valid")]
    avg_penalty = (sum(float(r["penalty_score"]) for r in good) / len(good)) if good else float("inf")
    return {
        "runs": runs, "avg_penalty": avg_penalty,
        "valid_count": len(good), "count": len(runs),
        "total_elapsed_ms": round(sum(max(0, int(r.get("elapsed_ms", 0))) for r in runs), 1),
    }
