"""L4: the agent rewrites solver FUNCTIONS (not just CONFIG) in a sandbox.

Lifecycle of one code patch:
  1. pick a target from the whitelist (local_search, strategy_key, ...);
  2. LLM writes a full replacement function (JSON {code, rationale});
  3. static validation -- single top-level FunctionDef, exact signature, no
     imports/global/nonlocal/yield/try/with, no dangerous names, no dunder
     attribute access, no audit-DANGER substrings;
  4. materialize a patched COPY of solver.py in variants/ (compile-checked);
  5. sandbox smoke + screening + full-budget validation + protected gate run
     that copy through the normal runner (subprocess, hard timeout);
  6. promotion splices ONLY the function's line span into submission/solver.py
     (config_io-style surgery, backup + smoke + revert on failure).

The subprocess sandbox is the real safety boundary: a hostile or buggy patch
can only waste CPU inside one worker process and will fail the evaluator/gates.
AST validation exists to reject obviously doomed patches before spending runs.
"""
from __future__ import annotations

import ast
import difflib
import json
import re
from pathlib import Path

from . import llm

ROOT = Path(__file__).resolve().parent.parent
SOLVER_PATH = ROOT / "submission" / "solver.py"
VARIANTS_DIR = ROOT / "variants"

AUDIT_DANGER = ["requests", "openai", "deepseek", "sqlite", "langgraph",
                "pandas", "scipy", "os.system", "socket"]

# Rotation of mutable targets; descriptions feed the synthesis prompt.
# local_search is listed first and is the tournament target (N parallel patches).
TARGETS = ["local_search", "improve_low_with_multi_options", "improve_regular_with_multi_options",
           "choose_probability_backups", "greedy_select", "improve_backup_allocation"]
TARGET_NOTES = {
    "local_search": "core improve loop: remove/replace/exact-cover moves under a wall-clock budget; returns (current, current_eval)",
    "strategy_key": "greedy ordering rank function built from a weight spec tuple; returns a key function for sorted()",
    "choose_probability_backups": "picks multi-courier backups per selected bundle to minimize expected penalty; returns dict",
    "rank_removals": "orders selected bundles for removal during repair; returns sorted list",
    "greedy_select": "greedily picks non-conflicting candidates from a pre-ordered list; returns the selected list",
    "improve_low_with_multi_options": "builds multi-courier backup options for low-willingness scenes; returns (selected, backup_map)",
    "improve_regular_with_multi_options": "backup topology improvement for normal scenes; may delegate to improve_regular_legacy_multi_options; returns (selected, backup_map)",
    "improve_backup_allocation": "reallocates backup couriers across selected bundles; returns (selected, backup_map)",
}

# Menu items used to diversify tournament patches (one focus per attempt).
MENU = [
    "simulated-annealing / record-to-record acceptance",
    "perturbation restarts with best-so-far retention",
    "move distribution change (regret- or gain-biased sampling)",
    "batching several candidate replacements per removal",
    "pruning moves that cannot beat the current eval by a margin",
]

DENIED_NAMES = {"open", "eval", "exec", "compile", "__import__", "input", "globals",
                "locals", "vars", "setattr", "getattr", "delattr", "breakpoint",
                "help", "dir", "exit", "quit", "os", "sys", "socket", "subprocess",
                "shutil", "urllib", "requests", "pathlib", "Path", "importlib"}
# Try/Nonlocal/Raise/Assert are ALLOWED: realistic algorithm patches use
# try/except for robustness and nonlocal for nested-helper state. The sandbox
# (subprocess + external scoring + gates) is the actual security boundary;
# still denied: imports, global writes, yield/await, with (file handles).
DENIED_NODES = (ast.Import, ast.ImportFrom, ast.Global, ast.Yield,
                ast.YieldFrom, ast.Await, ast.With)


def top_level_function_names(source: str) -> list[str]:
    return [n.name for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)]


def function_signatures(source: str) -> list[str]:
    out = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef):
            args = ", ".join(a.arg for a in node.args.args)
            out.append(f"def {node.name}({args})")
    return out


def class_summaries(source: str) -> list[str]:
    """Field summaries of the small data classes (Candidate/Context/Eval)."""
    out = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef):
            fields = []
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    fields.append(stmt.target.id)
                elif isinstance(stmt, ast.Assign):
                    for t in stmt.targets:
                        if isinstance(t, ast.Name):
                            fields.append(t.id)
            out.append(f"class {node.name}: {', '.join(fields)}")
    return out


def extract_function(source: str, name: str) -> tuple[int, int, str] | None:
    """(start_line, end_line) 1-based inclusive + exact source text."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            lines = source.splitlines(keepends=True)
            return node.lineno, node.end_lineno, "".join(lines[node.lineno - 1:node.end_lineno])
    return None


def splice_function(source: str, name: str, new_code: str) -> str:
    span = extract_function(source, name)
    if span is None:
        raise ValueError(f"function {name} not found")
    start, end, _ = span
    if not new_code.endswith("\n"):
        new_code += "\n"
    lines = source.splitlines(keepends=True)
    new_source = "".join(lines[:start - 1]) + new_code + "".join(lines[end:])
    compile(new_source, "<patched>", "exec")
    check = extract_function(new_source, name)
    if check is None:
        raise ValueError("splice lost the function")
    return new_source


def validate_patch(code: str, func_name: str, expected_args: list[str]) -> tuple[bool, str]:
    for keyword in AUDIT_DANGER:
        if keyword in code:
            return False, f"contains audit-danger substring: {keyword}"
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"syntax error: {exc}"
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if len(funcs) != 1 or funcs[0].name != func_name:
        return False, "patch must define exactly one top-level function with the target name"
    args = [a.arg for a in funcs[0].args.args]
    if args != expected_args:
        return False, f"signature must be {expected_args}, got {args}"
    for node in ast.walk(tree):
        if isinstance(node, DENIED_NODES):
            return False, f"construct not allowed: {type(node).__name__}"
        if isinstance(node, ast.Name) and node.id in DENIED_NAMES:
            return False, f"name not allowed: {node.id}"
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return False, f"dunder attribute not allowed: .{node.attr}"
    return True, "ok"


def expected_signature(source: str, name: str) -> list[str] | None:
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return [a.arg for a in node.args.args]
    return None


def materialize_variant(source: str, func_name: str, new_code: str, tag: str) -> Path:
    VARIANTS_DIR.mkdir(parents=True, exist_ok=True)
    patched = splice_function(source, func_name, new_code)
    path = VARIANTS_DIR / f"l4_{func_name}_{tag}.py"
    path.write_text(patched, encoding="utf-8", newline="")
    return path


CODE_SYSTEM = (
    "You are the Code Evolution Agent (L4) of a self-improving solver studio. "
    "Rewrite ONE function of a courier-task assignment solver so it produces "
    "BETTER solutions within the same wall-clock budget.\n"
    "CONTRACT: identical function name and parameter names; no imports; use only "
    "the module names listed (helper functions, the data classes' fields, CONFIG, "
    "itertools/random/time); respect the deadline system -- stop when "
    "_has_time(deadline_ms) is false; return exactly the same type/shape.\n"
    "A patch that is semantically equivalent to the original is a FAILURE. Pick "
    "at least one substantial algorithmic change from this menu and implement it:\n"
    "  - acceptance: simulated-annealing / record-to-record travel instead of "
    "strict improvement;\n"
    "  - restarts: perturb the incumbent (random removals) and re-improve when "
    "stuck, keeping the best-so-far;\n"
    "  - move distribution: bias move sampling by regret or by removal gain "
    "instead of round-robin over positions;\n"
    "  - batching: try several candidate replacements per removal in one pass;\n"
    "  - pruning: skip moves that cannot beat the current eval by a margin.\n"
    "Keep it deadline-safe: check `_now_ms() - start_ms > budget or not "
    "_has_time(deadline_ms)` inside every loop; spend the budget the original "
    "was given, no more.\n"
    'Reply JSON only: {"code": "<full replacement function source>", '
    '"rationale": "<=80 words, name the menu item you chose>"}.'
)


ARCHIVE_DIR = ROOT / "memory" / "l4_archive"


def archive_patch(target: str, scene: str, focus: str | None, code: str,
                  rationale: str, screen_avg: float, baseline_avg: float) -> Path:
    """Persist a screening-cleared patch for retry after gate/prompt changes."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    import time as _time
    path = ARCHIVE_DIR / f"{target}_{scene}_{int(_time.time() * 1000) % 10 ** 9}.json"
    path.write_text(json.dumps({
        "target": target, "scene": scene, "focus": focus, "code": code,
        "rationale": rationale, "screen_avg": screen_avg, "baseline_avg": baseline_avg,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_archived(target: str, scene: str, limit: int = 2) -> list[dict]:
    if not ARCHIVE_DIR.exists():
        return []
    out = []
    for p in sorted(ARCHIVE_DIR.glob(f"{target}_{scene}_*.json"), reverse=True)[:limit]:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def drop_archive(target: str, scene: str) -> None:
    """Remove archived patches once one has been promoted (they are obsolete)."""
    for p in (ARCHIVE_DIR.glob(f"{target}_{scene}_*.json") if ARCHIVE_DIR.exists() else []):
        p.unlink(missing_ok=True)


def synthesize_patch(root: Path, func_name: str, rnd: int, exp, focus: str | None = None) -> dict:
    root = Path(root)
    ok, desc = llm.available()
    if not ok:
        return {"ok": False, "reason": f"LLM key 未配置，跳过 L4（{llm.LAST_ERROR or 'no key'}）。"}
    solver_path = root / "submission" / "solver.py"
    source = solver_path.read_text(encoding="utf-8")
    span = extract_function(source, func_name)
    if span is None:
        return {"ok": False, "reason": f"目标函数 {func_name} 不存在。"}
    _s, _e, target_source = span
    expected_args = expected_signature(source, func_name)
    user = json.dumps({
        "target_function": func_name,
        "target_contract": TARGET_NOTES.get(func_name, ""),
        "current_source": target_source,
        "available_functions": function_signatures(source),
        "domain_types": class_summaries(source),
        "recent_trials": [dict(r) for r in exp.db.execute(
            "SELECT round, scene, op, gain_pct, decision FROM trials ORDER BY id DESC LIMIT 6")],
        "round": rnd,
        "focus": (f"This attempt MUST implement the '{focus}' menu item as its main "
                  "change -- competing patches implement the other menu items.") if focus
                  else "Pick the menu item you judge most promising for this function.",
    }, ensure_ascii=False)
    parsed = llm._extract_json(llm._chat(CODE_SYSTEM, user, timeout=120, temperature=0.9) or "")
    if not parsed or not parsed.get("code"):
        reason = "LLM 未返回可解析的补丁 JSON。"
        if llm.LAST_ERROR:
            reason += f" API 错误：{llm.LAST_ERROR}"
        return {"ok": False, "reason": reason}
    code = str(parsed["code"])
    fence = re.search(r"```[a-zA-Z]*\n(.*?)```", code, re.S)
    if fence:
        code = fence.group(1)
    good, why = validate_patch(code, func_name, expected_args)
    if not good:
        return {"ok": False, "reason": f"AST 白名单拒绝：{why}", "name": func_name}
    # Equivalence guard: near-identical rewrites waste a screen run; bounce them
    # back so the next attempt picks a bolder change.
    similarity = difflib.SequenceMatcher(None, target_source, code).ratio()
    if similarity > 0.90:
        return {"ok": False, "name": func_name,
                "reason": f"补丁与原实现相似度 {similarity:.0%}，过于保守（等价改写是失败），已打回。"}
    return {"ok": True, "name": func_name, "code": code,
            "rationale": str(parsed.get("rationale", ""))[:300]}
