"""Subprocess worker for learned (self-written) proposal operators.

Usage: python agent_core/operator_worker.py <job_json_path>
Job: {"op_path": ..., "config": {...}, "scene": "...", "seed": int}
Out: {"ok": true, "overrides": {...}} or {"ok": false, "error": "..."}
"""
from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path


def main() -> None:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        spec = importlib.util.spec_from_file_location("learned_op", job["op_path"])
        module = importlib.util.module_from_spec(spec)
        sys.modules["learned_op"] = module
        spec.loader.exec_module(module)
        rng = random.Random(int(job.get("seed", 0)))
        overrides = module.mutate_config(dict(job["config"]), str(job["scene"]), rng)
        if not isinstance(overrides, dict):
            raise TypeError(f"mutate_config returned {type(overrides).__name__}, expected dict")
        clean = {}
        for key, value in overrides.items():
            if isinstance(value, (int, float, bool, str, list, tuple)):
                clean[str(key)] = value
        sys.stdout.write(json.dumps({"ok": True, "overrides": clean}))
    except Exception as exc:  # noqa: BLE001 - report as JSON, never crash the parent
        sys.stdout.write(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))


if __name__ == "__main__":
    main()
