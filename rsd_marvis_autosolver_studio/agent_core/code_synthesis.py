"""RSI level 3: the agent synthesizes NEW proposal-operator code for itself.

A learned operator is a Python file defining `mutate_config(config, scene, rng)
-> dict`. Lifecycle:
  1. LLM writes candidate code (JSON {name, code});
  2. static AST validation -- whitelisted syntax only, no imports/IO/network/
     dunder access, only rng methods and config.get;
  3. sandbox smoke runs in a subprocess (operator_worker.py, hard timeout)
     against several configs/seeds; proposals must pass mutations.validate_
     overrides, so even a hostile operator can only emit bounded CONFIG keys;
  4. surviving operators are registered (learned_operators/registry.json) and
     join the UCB pool in operators.py -- the improver has improved itself.

Deterministic fallback: without an API key synthesis is skipped and levels
1-2 (solver write-back + bandit policy learning) keep running.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import time
from pathlib import Path

from . import llm, mutations

ROOT = Path(__file__).resolve().parent.parent
LEARNED_DIR = ROOT / "agent_core" / "learned_operators"
WORKER = ROOT / "agent_core" / "operator_worker.py"
REGISTRY = LEARNED_DIR / "registry.json"
SMOKE_TIMEOUT_S = 8.0

SYNTH_SYSTEM = (
    "You are the meta-programmer of a self-improving solver studio. Write ONE new "
    "proposal operator as a Python function:\n"
    "    def mutate_config(config, scene, rng):\n"
    "        ...return {\"<config_key>\": value, ...}\n"
    "It proposes small CONFIG overrides for a courier-task assignment solver.\n"
    "HARD RULES: no imports; no I/O; no attribute access except rng.random(), "
    "rng.uniform(a,b), rng.choice(seq), rng.randrange(a), rng.getrandbits(k) and "
    "config.get(key, default); use only float/int/round/min/max/abs/len/str/bool "
    "and literals; only propose keys from the whitelist, within the given bounds; "
    "make the operator DETERMINISTIC-GOOD: targeted, scene-aware, based on the "
    "given operator statistics. Return JSON only: "
    '{"name": "<snake_case_name>", "code": "<the full function source>"}.'
)

ALLOWED_CALLS = {"float", "int", "round", "min", "max", "abs", "len", "str", "bool"}
ALLOWED_RNG_METHODS = {"random", "uniform", "choice", "randrange", "getrandbits", "sample", "shuffle"}
DENIED_NAMES = {"eval", "exec", "open", "compile", "__import__", "input", "print",
                "globals", "locals", "vars", "setattr", "getattr", "delattr",
                "breakpoint", "help", "dir", "exit", "quit"}
ALLOWED_NODES = (
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Assign, ast.AugAssign,
    ast.AnnAssign, ast.Return, ast.If, ast.IfExp, ast.For, ast.Break, ast.Continue,
    ast.Expr, ast.Call, ast.Compare, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Constant,
    ast.Name, ast.Load, ast.Store, ast.Dict, ast.List, ast.Tuple, ast.keyword,
    ast.Subscript, ast.Slice, ast.Attribute, ast.DictComp, ast.ListComp,
    ast.comprehension,
    ast.operator, ast.unaryop, ast.boolop, ast.cmpop,
)


def validate_code(code: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"syntax error: {exc}"
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if len(funcs) != 1 or funcs[0].name != "mutate_config":
        return False, "module must define exactly one function: mutate_config"
    args = [a.arg for a in funcs[0].args.args]
    if args != ["config", "scene", "rng"]:
        return False, f"signature must be (config, scene, rng), got {args}"
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            return False, f"node not allowed: {type(node).__name__}"
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal,
                             ast.Yield, ast.Await, ast.Lambda, ast.Try, ast.With)):
            return False, f"construct not allowed: {type(node).__name__}"
        if isinstance(node, ast.Name) and node.id in DENIED_NAMES:
            return False, f"name not allowed: {node.id}"
        if isinstance(node, ast.Attribute):
            owner = node.value
            if isinstance(owner, ast.Name) and owner.id == "rng" and \
                    node.attr in ALLOWED_RNG_METHODS:
                continue
            if isinstance(owner, ast.Name) and owner.id == "config" and node.attr == "get":
                continue
            return False, f"attribute access not allowed: .{node.attr}"
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in ALLOWED_CALLS:
                continue
            if isinstance(func, ast.Attribute):
                continue  # already whitelist-checked above
            return False, "call target not allowed"
    return True, "ok"


def sandbox_run(op_path: str | Path, config: dict, scene: str, seed: int) -> tuple[bool, dict | None, str]:
    job_path = LEARNED_DIR / f"_job_{int(time.time()*1000)}.json"
    job_path.parent.mkdir(parents=True, exist_ok=True)
    job_path.write_text(json.dumps({
        "op_path": str(op_path), "config": config, "scene": scene, "seed": seed,
    }, ensure_ascii=False), encoding="utf-8")
    try:
        proc = subprocess.run([sys.executable, str(WORKER), str(job_path)],
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=SMOKE_TIMEOUT_S, cwd=str(ROOT))
        out = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
    except subprocess.TimeoutExpired:
        return False, None, "sandbox timeout (possible infinite loop)"
    except Exception as exc:  # noqa: BLE001
        return False, None, f"sandbox error: {exc}"
    finally:
        job_path.unlink(missing_ok=True)
    if not out.get("ok"):
        return False, None, out.get("error", "worker failed")
    return True, out.get("overrides") or {}, "ok"


def load_registry(root: Path | None = None) -> dict[str, dict]:
    base = Path(root) if root else ROOT
    reg = base / "agent_core" / "learned_operators" / "registry.json"
    try:
        data = json.loads(reg.read_text(encoding="utf-8"))
        return {d["name"]: d for d in data.get("operators", []) if not d.get("retired")}
    except Exception:
        return {}


def _extract_code_block(text: str) -> str | None:
    if not text:
        return None
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("python"):
                part = part[6:]
            if "def mutate_config" in part:
                return part.strip()
    return text.strip() if "def mutate_config" in text else None


def synthesize(root: Path | str, scene: str, rnd: int, exp) -> dict:
    """One meta step: try to grow the operator pool. Returns a report dict."""
    root = Path(root)
    ok, desc = llm.available()
    if not ok:
        return {"ok": False, "reason": "LLM key 未配置，跳过算子合成（L1/L2 继续运行）。"}
    from . import config_io
    try:
        config = config_io.read_config(root / "submission" / "solver.py")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"无法读取 CONFIG：{exc}"}
    whitelist = {k: mutations.BOUNDS[k] for k in mutations.SCENE_KEYS.get(scene, [])
                 if k in mutations.BOUNDS}
    user = json.dumps({
        "scene": scene, "round": rnd,
        "whitelist_and_bounds": {k: [b[0], b[1], b[2]] for k, b in whitelist.items()},
        "operator_stats": exp.op_stats(),
        "recent_trials": [dict(r) for r in exp.db.execute(
            "SELECT round, scene, op, gain_pct, decision FROM trials ORDER BY id DESC LIMIT 8")],
        "known_weakness": "propose an operator that targets the scene's worst metric",
    }, ensure_ascii=False)
    parsed = llm._extract_json(llm._chat(SYNTH_SYSTEM, user, timeout=60) or "")
    if not parsed or not parsed.get("code"):
        reason = "LLM 未返回可解析的算子 JSON。"
        if llm.LAST_ERROR:
            reason += f" API 错误：{llm.LAST_ERROR}"
        return {"ok": False, "reason": reason}
    name = "".join(c for c in str(parsed.get("name", "op_custom")) if c.isalnum() or c == "_")[:40]
    code = _extract_code_block(str(parsed["code"])) or str(parsed["code"])
    good, why = validate_code(code)
    if not good:
        return {"ok": False, "reason": f"AST 白名单拒绝：{why}", "name": name}
    LEARNED_DIR.mkdir(parents=True, exist_ok=True)
    op_path = LEARNED_DIR / f"op_{name}.py"
    if name in load_registry(root):
        name = f"{name}_r{rnd}"
        op_path = LEARNED_DIR / f"op_{name}.py"
    op_path.write_text(code, encoding="utf-8")

    # -- smoke: several seeds; proposals must exist and pass the whitelist ------
    proposed_any, sample = False, {}
    for seed in (1, 42, 20260919):
        good_run, overrides, err = sandbox_run(op_path, config, scene, seed)
        if not good_run:
            op_path.unlink(missing_ok=True)
            return {"ok": False, "reason": f"沙箱冒烟失败（seed={seed}）：{err}", "name": name}
        accepted, rejected = mutations.validate_overrides(config, scene, overrides)
        if accepted:
            proposed_any = True
            sample = accepted
    if not proposed_any:
        op_path.unlink(missing_ok=True)
        return {"ok": False, "reason": "算子在多种子下从未提出有效键，拒绝注册。", "name": name}

    reg_path = LEARNED_DIR / "registry.json"
    try:
        registry = json.loads(reg_path.read_text(encoding="utf-8"))
    except Exception:
        registry = {"operators": []}
    registry["operators"].append({"name": name, "file": op_path.name, "scene": scene,
                                  "born_round": rnd, "created_at":
                                  time.strftime("%Y-%m-%d %H:%M:%S")})
    reg_path.write_text(json.dumps(registry, ensure_ascii=False, indent=1), encoding="utf-8")
    exp.register_operator(name, "synthesized", rnd)
    return {"ok": True, "name": name, "sample_proposal": sample,
            "reason": f"新算子已注册并加入 UCB 池（{op_path.name}）"}
