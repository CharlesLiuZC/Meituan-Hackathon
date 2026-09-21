"""Subprocess worker: run submission/solver.py on one case with CONFIG overrides.

Usage: python agent_core/solver_worker.py <job_json_path>
Job JSON: {"solver_path": ..., "case_path": ..., "overrides": {...}, "time_budget_ms": ...}
Prints one JSON line to stdout: {"ok": true, "solution": [...], "elapsed_ms": ...}
or {"ok": false, "error": "..."}.

Subprocess isolation gives a hard kill on runaway solves and avoids the
module-global CONFIG racing between candidate evaluations.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

# Keys the training loop is never allowed to touch (official semantics / stability).
PROTECTED_KEYS = {"acceptance_penalty", "_runtime_case_type"}


def load_solver_module(solver_path: str):
    solver_path = str(Path(solver_path).resolve())
    spec = importlib.util.spec_from_file_location("studio_solver_under_test", solver_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["studio_solver_under_test"] = module
    spec.loader.exec_module(module)
    return module


def apply_overrides(module, overrides: dict) -> list[str]:
    config = getattr(module, "CONFIG", {})
    skipped = []
    for key, value in (overrides or {}).items():
        if key in PROTECTED_KEYS or key.startswith("_") or key not in config:
            skipped.append(key)
            continue
        if type(value) is not type(config[key]):
            try:  # allow int->float widening only
                if not (isinstance(value, int) and isinstance(config[key], float)):
                    skipped.append(key)
                    continue
                value = float(value)
            except Exception:
                skipped.append(key)
                continue
        config[key] = value
    return skipped


def main() -> None:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    input_text = Path(job["case_path"]).read_text(encoding="utf-8", errors="ignore")
    module = load_solver_module(job["solver_path"])
    skipped = apply_overrides(module, job.get("overrides") or {})
    if job.get("time_budget_ms"):
        module.CONFIG["time_budget_ms"] = float(job["time_budget_ms"])
    start = time.perf_counter()
    try:
        solution = module.solve(input_text)
        ok = True
        error = None
    except Exception as exc:  # noqa: BLE001 - report any solver failure as JSON
        solution = None
        ok = False
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = round((time.perf_counter() - start) * 1000.0, 1)
    out = {
        "ok": ok,
        "elapsed_ms": elapsed_ms,
        "case_type": module.CONFIG.get("_runtime_case_type"),
        "skipped_overrides": skipped,
    }
    if ok:
        out["solution"] = solution
    else:
        out["error"] = error
    sys.stdout.write(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
