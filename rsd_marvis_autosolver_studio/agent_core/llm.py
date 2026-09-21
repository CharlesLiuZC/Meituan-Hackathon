"""LLM roles for the training loop (DeepSeek-compatible, optional).

The LLM never writes solver code. It proposes CONFIG overrides (validated by
mutations.validate_overrides before anything runs) and attributes failures in
plain language. Without an API key everything degrades to deterministic search.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

PROPOSE_SYSTEM = (
    "You are the Strategy Agent of an AutoSolver studio. You tune a courier-task "
    "assignment solver by proposing small CONFIG overrides. Reply with JSON only: "
    '{"overrides": {"<config_key>": <number|bool>}, "rationale": "<=80 words"}. '
    "Propose at most 3 keys from the whitelist. Keep changes incremental."
)

ATTR_SYSTEM = (
    "You are the LLM Reflector of an AutoSolver studio. Given trial statistics, "
    "attribute in <=120 words why the candidate failed to beat the baseline and "
    "what to try next. Reply in Chinese, plain text."
)


def available() -> tuple[bool, str]:
    key = os.getenv("DEEPSEEK_API_KEY", "")
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    return bool(key), f"{base}|{model}"


LAST_ERROR = None  # last API failure reason, surfaced by callers for honest diagnostics


def _chat(system: str, user: str, timeout: int = 30, temperature: float = 0.2) -> str | None:
    global LAST_ERROR
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key:
        LAST_ERROR = "DEEPSEEK_API_KEY 未设置"
        return None
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    payload = {"model": model, "temperature": temperature,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}]}
    req = urllib.request.Request(
        base + "/chat/completions", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return data.get("choices", [{}])[0].get("message", {}).get("content") or None
    except Exception as exc:  # noqa: BLE001 - report via LAST_ERROR, never crash training
        LAST_ERROR = f"{type(exc).__name__}: {exc}"
        return None


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    text = re.sub(r"```[a-zA-Z]*", "", text)  # strip markdown code fences
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def propose_overrides(scene: str, whitelist: list[str], current_config: dict,
                      recent_trials: list[dict]) -> tuple[dict, str] | None:
    """Returns ({key: value}, rationale) or None (no key / call failed / bad JSON)."""
    ok, _ = available()
    if not ok:
        return None
    compact_config = {k: v for k, v in current_config.items() if not str(k).startswith("_")}
    user = json.dumps({
        "scene": scene,
        "whitelist": whitelist,
        "current_config": compact_config,
        "recent_trials": recent_trials[-6:],
    }, ensure_ascii=False)
    parsed = _extract_json(_chat(PROPOSE_SYSTEM, user) or "")
    if not parsed or not isinstance(parsed.get("overrides"), dict):
        return None
    overrides = {str(k): v for k, v in parsed["overrides"].items() if isinstance(v, (int, float, bool))}
    return overrides, str(parsed.get("rationale", ""))[:300]


def attribute_failure(context: dict) -> str | None:
    ok, _ = available()
    if not ok:
        return None
    return (_chat(ATTR_SYSTEM, json.dumps(context, ensure_ascii=False)) or "")[:600] or None


STRATEGY_SYSTEM = (
    "You are the Strategy Evolution Agent of an AutoSolver studio. The solver's greedy "
    "ordering uses weight tuples (score_w, per_task_w, willing_w, bundle_w, scarcity_w, "
    "courier_w, bundle_first): rank = score_w*norm_score + per_task_w*norm_score_per_task "
    "- willing_w*willingness - bundle_w*(task_count-1) + scarcity_w*task_scarcity + "
    "courier_w*courier_pressure; bundle_first (0/1) forces bundles before singles. "
    "Lower rank is picked first. Propose a COMPLETE replacement list of 3-6 tuples "
    "(keeping the best existing ones you want, evolving the rest). Weights in [-2, 2]. "
    "Reply JSON only: {\"strategies\": [[...7 numbers], ...], \"rationale\": \"<=80 words\"}."
)


def propose_strategies(scene: str, current_strategies: list, recent_trials: list) -> tuple[list, str] | None:
    """Returns (list_of_tuples, rationale) or None."""
    ok, _ = available()
    if not ok:
        return None
    user = json.dumps({
        "scene": scene,
        "current_strategies": current_strategies,
        "recent_trials": recent_trials[-6:],
        "hint": "explore a genuinely different ordering region, not a tiny jitter",
    }, ensure_ascii=False)
    parsed = _extract_json(_chat(STRATEGY_SYSTEM, user, timeout=60) or "")
    if not parsed or not isinstance(parsed.get("strategies"), list):
        return None
    strategies = parsed["strategies"]
    return strategies, str(parsed.get("rationale", ""))[:300]
