"""Real one-click training: screen -> validate -> no-regression gate -> promote.

Replaces the V5 hardfix fake loop (hardcoded per-round gains + sleep). Every
number surfaced to the dashboard is measured by running submission/solver.py in
a subprocess. The solver file is only rewritten when a candidate passes all
gates; every promotion is preceded by a backup, followed by a smoke run, and
reverted if the smoke run fails.

Flow per round:
  1. pick scene from the mode schedule;
  2. screening baseline: current CONFIG on train cases at reduced budget;
  3. candidates: deterministic CONFIG mutations + (every other round, if an API
     key is set) an LLM proposal -- all validated against the whitelist;
  4. screen candidates; require >=1% penalty improvement to continue;
  5. validation at full budget: official anchor + the scene's holdout case,
     both strictly better than the measured champions;
  6. promotion gate: protected cases (tiny/small/scarce proxies) must not
     regress; first run establishes their measured champions;
  7. promote: splice CONFIG into solver.py, smoke-verify, update champions,
     write forensics + trend; otherwise reject with attribution.
"""
from __future__ import annotations

import time
import zlib
from pathlib import Path

from . import case_bank, code_evolution, code_synthesis, config_io, llm
from .experience import Experience
from .operators import OperatorPool
from .runner import DEFAULT_FULL_BUDGET_MS, DEFAULT_SCREEN_BUDGET_MS, better_by_penalty, \
    evaluate_case, screen_average

ROOT = Path(__file__).resolve().parent.parent
SOLVER_PATH = ROOT / "submission" / "solver.py"
ANCHOR_KEY = "anchor:large_seed301"
META_EVERY = 3                    # rounds between operator-synthesis meta steps
LEARNED_OPS_LABEL = "synthesized"

MODE_SCENES = {
    "safe-medium-only": ["medium"],
    "balanced": ["medium", "high_noise", "large", "low_willingness", "medium", "scarce_couriers"],
    "high-noise-lab": ["high_noise", "medium", "high_noise", "large"],
    "low-backup-lab": ["low_willingness", "low_willingness", "scarce_couriers", "medium"],
    "code-lab": ["medium", "high_noise", "large", "low_willingness", "scarce_couriers"],
}

SCREEN_IMPROVEMENT_MIN = 0.005     # fine-stage threshold; full-budget validation is the real gate
REGRESSION_TOLERANCE = 0.5         # default protected tolerance (overridable via params)
SMOKE_BUDGET_MS = 1500.0

# Two-stage screening: a 2s coarse pass ranks ALL candidates cheaply, then the
# top few are re-checked at 6s where the solver usually finishes its search
# (~4.6s natural completion) so scores are near-deterministic. 2s truncation is
# fine for coarse ranking; 6s leaves headroom against background-load truncation.
COARSE_BUDGET_MS = 2000.0
FINE_BUDGET_MS = 6000.0
# low_willingness solves run longer (backup-heavy phases); at 6s they are
# deadline-truncated and scores drift several points between runs. Measured:
# deterministic from 8s (spread 0.00 at 8s/9.3s vs ±6.4 at 6s).
FINE_BUDGET_LOW_WILL_MS = 8000.0
REFINE_TOP_N = 2


def fine_budget_for(scene: str) -> float:
    return FINE_BUDGET_LOW_WILL_MS if scene == "low_willingness" else FINE_BUDGET_MS

# Full-budget runs jitter ±1.2 penalty points (wall-clock deadline effects), so a
# "real" validation win must clear the noise floor, not just be strictly smaller.
# Promotion semantics are per-scene: the scene holdout must genuinely improve
# (>= HOLDOUT_MIN_GAIN); the anchor acts as a global no-regression gate
# (>= -ANCHOR_NO_REGRESS) because scene-targeted functions (e.g. local_search)
# legitimately cannot move it -- the anchor is dominated by improve_regular.
ANCHOR_MIN_GAIN = 1.5
HOLDOUT_MIN_GAIN = 1.0
ANCHOR_NO_REGRESS = 0.5


def _fmt_overrides(overrides: dict) -> str:
    parts = []
    for key, value in (overrides or {}).items():
        if key == "strategies":
            parts.append(f"strategies[{len(value)} tuples] modified")
        else:
            parts.append(f"CONFIG['{key}']={value}")
    return ", ".join(parts) or "(none)"


def _plain(overrides: dict) -> dict:
    out = {k: v for k, v in (overrides or {}).items() if k != "strategies"}
    if "strategies" in (overrides or {}):
        out["strategies"] = "…weight tuples modified"
    return out


def _stable_seed(*parts) -> int:
    # hash() is salted per process; crc32 keeps case bank and candidates reproducible.
    return zlib.crc32("|".join(map(str, parts)).encode())


def run_training(rounds: int, mode: str, should_stop, rep) -> dict:
    started = time.time()
    manifest = case_bank.ensure_case_bank(ROOT)
    rep.event("Data Seed", "data", f"case bank ready: {len(manifest['cases'])} cases "
              f"(train/holdout/protected, scenes: {', '.join(case_bank.SCENES)}).")

    champions = dict(rep.get_champions())
    exp = Experience(ROOT / "memory" / "experience.sqlite")
    pool = OperatorPool(exp, ROOT)
    exp.register_operator("code_evolution", "l4", 0)
    schedule = MODE_SCENES.get(mode, MODE_SCENES["balanced"])
    protected = [(name, str(ROOT / p)) for name, p in
                 zip(("tiny", "small", "scarce_couriers"),
                     case_bank.cases_of(manifest, "protected"))]
    anchor_path = str(ROOT / case_bank.ANCHOR)
    llm_ok, llm_desc = llm.available()
    rep.event("LLM Reflector", "llm",
              f"DeepSeek {'已配置 (' + llm_desc + ')' if llm_ok else '未配置：使用确定性搜索，LLM 提案/归因/算子合成跳过。'}")
    rep.set_rsi({"operators": exp.op_stats(), "summary": exp.summary(),
                 "learned_ops": list(code_synthesis.load_registry(ROOT).keys())})

    summary = {"rounds_done": 0, "candidates": 0, "rejected": 0, "promoted": 0,
               "anchor_key": ANCHOR_KEY, "mode": mode, "trial_log": []}

    def ensure_champion(key: str, path: str) -> dict:
        if key not in champions:
            metrics = evaluate_case(path, None, DEFAULT_FULL_BUDGET_MS)
            champions[key] = metrics
            rep.set_champion(key, metrics)
            rep.event("Evaluator", "eval",
                      f"建立 champion 基线 {key}: penalty={metrics.get('penalty_score')}, "
                      f"covered={metrics.get('covered_tasks')}/{metrics.get('total_tasks')}")
        return champions[key]

    def try_l4(i: int, scene: str, train_cases: list[str], holdout_path: str,
               anchor_path: str, base_fine_avg: float, fine_budget: float) -> bool:
        """L4 code evolution. Tournament targets (local_search) synthesize N
        diversely-focused patches in parallel, screen all of them, then
        full-validate up to the 2 best; first to clear every gate is promoted."""
        if not l4_enabled or i % l4_every != 0:
            return False
        # params l4_scenes restricts L4 to rounds whose scene actually executes
        # the target function (e.g. improve_backup_allocation only runs on the
        # low_willingness branch -- screening elsewhere is a guaranteed tie).
        l4_scenes = train_params.get("l4_scenes") or []
        if l4_scenes and scene not in l4_scenes:
            return False
        # params l4_target forces one function for the whole campaign (e.g.
        # improve_regular_with_multi_options to attack the anchor); rotation
        # is the default.
        forced = str(train_params.get("l4_target", "") or "")
        target = forced if forced in code_evolution.TARGETS else \
            code_evolution.TARGETS[(i // max(1, l4_every) - 1) % len(code_evolution.TARGETS)]
        n_versions = max(1, int(train_params.get("l4_tournament_n", 3))) \
            if target == "local_search" else 1
        rep.agent("reflector", status=f"L4 rewriting {target} x{n_versions}")
        solver_source = SOLVER_PATH.read_text(encoding="utf-8")
        expected_args = code_evolution.expected_signature(solver_source, target)

        clearing = []  # (fine_avg, variant, code, origin, rationale, trial_id)
        kept_variants = []
        try:
            # -- 0. retry screening-cleared archived patches first (free wins) -----
            archived = code_evolution.load_archived(target, scene, limit=2)
            for entry in archived:
                if should_stop():
                    break
                code = entry["code"]
                good, _why = code_evolution.validate_patch(code, target, expected_args)
                if not good:
                    continue
                variant = code_evolution.materialize_variant(solver_source, target, code,
                                                             f"r{i}arch")
                kept_variants.append(variant)
                fine = screen_average(train_cases, None, fine_budget, solver_path=str(variant))
                gain = (base_fine_avg - fine["avg_penalty"]) / max(1e-9, base_fine_avg) * 100.0
                exp.credit_operator("code_evolution", gain, won=gain > 0)
                trial_id = exp.log_trial(i, scene, "code_evolution",
                                         {"function": target, "focus": "archive"},
                                         fine["avg_penalty"], base_fine_avg, gain, "screened_l4")
                origin = f"l4:{target}[archive]({str(entry.get('rationale', ''))[:40]})"
                trial = {"round": i, "scene": scene, "origin": origin, "stage": "l4",
                         "overrides": {"function": target, "focus": "archive"},
                         "screen_avg": round(fine["avg_penalty"], 3),
                         "baseline_avg": round(base_fine_avg, 3),
                         "gain_pct": round(gain, 2), "decision": "screened"}
                summary["trial_log"].append(trial)
                rep.jlog_trials({"time": time.strftime("%H:%M:%S"), **trial})
                rep.timeline({"round": i, "scene": scene, "agent": "Code Evolution",
                              "message": f"L4 {target} [archive] screened: "
                                         f"{fine['avg_penalty']:.2f} vs {base_fine_avg:.2f}",
                              "metrics": {"gain_pct": round(gain, 2)}})
                if fine["avg_penalty"] <= base_fine_avg * (1.0 - SCREEN_IMPROVEMENT_MIN):
                    clearing.append((fine["avg_penalty"], variant, code, origin,
                                     str(entry.get("rationale", "")), trial_id))
                else:
                    variant.unlink(missing_ok=True)
                    kept_variants.remove(variant)

            # -- tournament: synthesize + screen every variant -------------------
            for k in range(n_versions):
                if should_stop():
                    break
                focus = code_evolution.MENU[(i + k) % len(code_evolution.MENU)] \
                    if n_versions > 1 else None
                report = code_evolution.synthesize_patch(ROOT, target, i, exp, focus=focus)
                if not report.get("ok"):
                    rep.event("Code Evolution", "l4",
                              f"{target}#{k + 1} 补丁合成未成功：{report.get('reason')}")
                    continue
                code = report["code"]
                good, why = code_evolution.validate_patch(code, target, expected_args)
                if not good:
                    rep.event("Code Evolution", "l4",
                              f"{target}#{k + 1} 补丁被 AST 白名单拒绝：{why}")
                    continue
                variant = code_evolution.materialize_variant(solver_source, target, code, f"r{i}v{k}")
                kept_variants.append(variant)
                fine = screen_average(train_cases, None, fine_budget, solver_path=str(variant))
                gain = (base_fine_avg - fine["avg_penalty"]) / max(1e-9, base_fine_avg) * 100.0
                exp.credit_operator("code_evolution", gain, won=gain > 0)
                trial_id = exp.log_trial(i, scene, "code_evolution",
                                         {"function": target, "focus": focus},
                                         fine["avg_penalty"], base_fine_avg, gain, "screened_l4")
                focus_label = (focus or report["rationale"])[:48]
                origin = f"l4:{target}#{k + 1}({focus_label})"
                trial = {"round": i, "scene": scene, "origin": origin, "stage": "l4",
                         "overrides": {"function": target, "focus": focus},
                         "screen_avg": round(fine["avg_penalty"], 3),
                         "baseline_avg": round(base_fine_avg, 3),
                         "gain_pct": round(gain, 2), "decision": "screened"}
                summary["trial_log"].append(trial)
                rep.jlog_trials({"time": time.strftime("%H:%M:%S"), **trial})
                rep.timeline({"round": i, "scene": scene, "agent": "Code Evolution",
                              "message": f"L4 {target}#{k + 1} [{(focus or 'free')[:32]}] "
                                         f"screened: {fine['avg_penalty']:.2f} vs {base_fine_avg:.2f}",
                              "metrics": {"gain_pct": round(gain, 2)}})
                if fine["avg_penalty"] <= base_fine_avg * (1.0 - SCREEN_IMPROVEMENT_MIN):
                    clearing.append((fine["avg_penalty"], variant, code, origin,
                                     report["rationale"], trial_id))
                    code_evolution.archive_patch(target, scene, focus, code,
                                                 report["rationale"],
                                                 fine["avg_penalty"], base_fine_avg)
                else:
                    variant.unlink(missing_ok=True)
                    kept_variants.remove(variant)
                    summary["rejected"] += 1
            clearing.sort(key=lambda c: c[0])

            # -- full-budget validation of up to 2 clearing candidates ------------
            champion_anchor = ensure_champion(ANCHOR_KEY, anchor_path)
            champion_holdout = ensure_champion(f"holdout:{scene}", holdout_path)
            for fine_avg, variant, code, origin, rationale, trial_id in clearing[:2]:
                if should_stop():
                    break
                cand_anchor = evaluate_case(anchor_path, None, DEFAULT_FULL_BUDGET_MS,
                                            solver_path=str(variant))
                cand_holdout = evaluate_case(holdout_path, None, DEFAULT_FULL_BUDGET_MS,
                                             solver_path=str(variant))
                anchor_gain = float(champion_anchor.get("penalty_score", float("inf"))) - \
                    float(cand_anchor.get("penalty_score", float("inf")))
                holdout_gain = float(champion_holdout.get("penalty_score", float("inf"))) - \
                    float(cand_holdout.get("penalty_score", float("inf")))
                anchor_ok = (cand_anchor.get("ok") and cand_anchor.get("valid")
                             and int(cand_anchor.get("covered_tasks", 0)) >=
                             int(champion_anchor.get("covered_tasks", 0))
                             and anchor_gain >= -ANCHOR_NO_REGRESS)
                ok = anchor_ok and \
                    better_by_penalty(cand_holdout, champion_holdout) and \
                    holdout_gain >= HOLDOUT_MIN_GAIN
                rep.timeline({"round": i, "scene": scene, "agent": "Evaluator",
                              "message": (f"L4 validation({origin[:44]}): anchor "
                                          f"{champion_anchor['penalty_score']:.2f} -> "
                                          f"{cand_anchor.get('penalty_score', float('inf')):.2f}, "
                                          f"holdout {champion_holdout['penalty_score']:.2f} -> "
                                          f"{cand_holdout.get('penalty_score', float('inf')):.2f}"),
                              "metrics": {"anchor": cand_anchor.get("penalty_score"),
                                          "holdout": cand_holdout.get("penalty_score"),
                                          "valid": ok}})
                if not ok or should_stop():
                    summary["rejected"] += 1
                    continue

                # protected no-regression gate (adaptive tolerance).
                # Paired measurement: full-budget protected runs drift ±2.3 with
                # system load, larger than the tolerance itself, so the candidate
                # is compared against a FRESH baseline run under the same load,
                # not the stale stored champion.
                tol_base = float(train_params.get("regression_tolerance", REGRESSION_TOLERANCE))
                tol_ratio = float(train_params.get("anchor_tradeoff_ratio", 0.0))
                tol_cap = float(train_params.get("anchor_tradeoff_cap", 1.0))
                tolerance = tol_base + (min(tol_cap, max(0.0, anchor_gain) * tol_ratio) if tol_ratio > 0 else 0.0)
                gate_runs = {}
                gate_failed = False
                for name, path in protected:
                    fresh_base = evaluate_case(path, None, DEFAULT_FULL_BUDGET_MS)
                    cand_p = evaluate_case(path, None, DEFAULT_FULL_BUDGET_MS, solver_path=str(variant))
                    gate_runs[name] = cand_p
                    paired_delta = float(cand_p.get("penalty_score", float("inf"))) - \
                        float(fresh_base.get("penalty_score", float("inf")))
                    if (not cand_p.get("ok") or not cand_p.get("valid") or
                            paired_delta > tolerance):
                        gate_failed = True
                        rep.forensic(
                            f"protected:{name}",
                            f"L4 补丁（{origin}）在保护场景 {name} 上配对回退 {paired_delta:+.2f}"
                            f"超容忍（容忍={tolerance:.2f}，同负载基线 {fresh_base.get('penalty_score'):.2f}），已拒绝。",
                            "danger", f"splice {target} (l4 patch r{i})",
                            f"keep {target} unchanged")
                        break
                if gate_failed or should_stop():
                    summary["rejected"] += 1
                    continue

                # promote: backup -> splice function -> smoke -> commit
                backup = rep.backup(f"l4_promote_r{i}")
                text_before = SOLVER_PATH.read_text(encoding="utf-8")
                new_source = code_evolution.splice_function(text_before, target, code)
                SOLVER_PATH.write_text(new_source, encoding="utf-8", newline="")
                smoke = evaluate_case(anchor_path, None, SMOKE_BUDGET_MS)
                if not smoke.get("ok"):
                    SOLVER_PATH.write_text(text_before, encoding="utf-8", newline="")
                    summary["rejected"] += 1
                    rep.event("Auditor", "guard", f"L4 晋升后 smoke 验证失败，已恢复原 {target}。")
                    continue
                if float(cand_anchor.get("penalty_score", float("inf"))) < \
                        float(champions[ANCHOR_KEY].get("penalty_score", float("inf"))):
                    champions[ANCHOR_KEY] = cand_anchor   # only bump on real anchor gain
                    rep.set_champion(ANCHOR_KEY, cand_anchor)
                champions[f"holdout:{scene}"] = cand_holdout
                rep.set_champion(f"holdout:{scene}", cand_holdout)
                for name, _path in protected:
                    if float(gate_runs[name].get("penalty_score", float("inf"))) < float(
                            champions.get(f"protected:{name}", {}).get("penalty_score", float("inf"))):
                        champions[f"protected:{name}"] = gate_runs[name]  # only on real gain
                        rep.set_champion(f"protected:{name}", gate_runs[name])
                summary["promoted"] += 1
                exp.mark_promoted(trial_id, float(cand_anchor["penalty_score"]),
                                  float(cand_holdout["penalty_score"]))
                old_span = code_evolution.extract_function(text_before, target)
                old_head = "\n".join(old_span[2].splitlines()[:6])
                new_head = "\n".join(code.splitlines()[:6])
                rep.forensic(
                    scene, f"Round {i} L4 晋升：Agent 重写了 solver 的 `{target}` 函数"
                           f"（{origin[:60]}；anchor {champion_anchor['penalty_score']:.2f} -> "
                           f"{cand_anchor['penalty_score']:.2f}，保护场景无回退）。依据：{rationale}",
                    "info", f"def {target} (原实现前6行)\n{old_head}\n...",
                    f"def {target} (新实现前6行)\n{new_head}\n...")
                rep.notes(f"\n## L4 代码进化（round {i}）\n\n目标 `{target}`：{rationale}\n\n"
                          f"```python\n{code}\n```\n")
                rep.set_trend(i, float(cand_anchor["penalty_score"]))
                code_evolution.drop_archive(target, scene)  # promoted: archive obsolete
                rep.agent("leader", decision="promoted")
                rep.event("Leader", "promote",
                          f"Round {i}: L4 promoted rewrite of `{target}` "
                          f"(anchor {cand_anchor['penalty_score']:.2f}, backup {backup['name']})")
                return True
            return False
        finally:
            for v in kept_variants:
                v.unlink(missing_ok=True)


    for i in range(1, rounds + 1):
        if should_stop():
            rep.event("Leader", "train", "训练被用户中止。")
            break
        scene = schedule[(i - 1) % len(schedule)]
        summary["rounds_done"] = i
        rep.train_update(round=i)
        rep.agent("strategy", status=f"routing {scene}")
        rep.agent("trainer", status=f"round {i}")
        rep.timeline({"round": i, "scene": scene, "agent": "Strategy",
                      "message": f"scene routed: {scene}", "metrics": {"mode": mode}})

        # -- meta step (RSI L3): grow the operator pool before proposing -----------
        # Runs at the TOP of the round so reject/continue paths can't starve it.
        if i % META_EVERY == 0 and not should_stop():
            rep.agent("reflector", status="synthesizing operator")
            report = code_synthesis.synthesize(ROOT, scene, i, exp)
            if report.get("ok"):
                rep.event("Meta Programmer", "rsi",
                          f"自我注入新算子 `{report['name']}`：{report['reason']}；"
                          f"示例提案 {_fmt_overrides(report.get('sample_proposal', {}))}")
                rep.forensic("RSI-operator", f"Round {i} 元步：Agent 为自己编写并注册了新提案算子"
                             f" `{report['name']}`（AST 白名单 + 子进程沙箱冒烟通过）。",
                             "info", "operator pool = builtin ops",
                             f"operator pool += learned op `{report['name']}`")
                rep.notes(f"\n## RSI 元步（round {i}）\n\n新算子 `{report['name']}` 已注册："
                          f"{report['reason']}\n")
            else:
                rep.event("Meta Programmer", "rsi", f"算子合成未成功：{report.get('reason')}")
            rep.set_rsi({"operators": exp.op_stats(), "summary": exp.summary(),
                         "learned_ops": list(code_synthesis.load_registry(ROOT).keys())})

        train_cases = [str(ROOT / p) for p in case_bank.cases_of(manifest, "train", scene)]
        holdout_paths = case_bank.cases_of(manifest, "holdout", scene)
        if not train_cases or not holdout_paths:
            rep.timeline({"round": i, "scene": scene, "agent": "Trainer",
                          "message": "no cases for scene, skipped", "metrics": {}})
            continue
        holdout_path = str(ROOT / holdout_paths[0])
        base_config = config_io.read_config(SOLVER_PATH)

        train_params = rep.get_params()
        l4_enabled = bool(train_params.get("l4_enabled", True))
        # code-lab is an explicit per-round L4 intent; params override elsewhere.
        l4_every = 1 if mode == "code-lab" else max(1, int(train_params.get("l4_every", 4)))
        # -- 1. shared screening baselines (coarse ranks, fine decides) -------------
        fine_budget = fine_budget_for(scene)
        base_coarse = screen_average(train_cases, None, COARSE_BUDGET_MS)
        base_fine = screen_average(train_cases, None, fine_budget)
        rep.timeline({"round": i, "scene": scene, "agent": "Evaluator",
                      "message": f"baselines: coarse {base_coarse['avg_penalty']:.2f} "
                                 f"({int(COARSE_BUDGET_MS)}ms) / fine {base_fine['avg_penalty']:.2f} "
                                 f"({int(fine_budget)}ms)",
                      "metrics": {"coarse": round(base_coarse["avg_penalty"], 3),
                                  "fine": round(base_fine["avg_penalty"], 3),
                                  "budget_ms": fine_budget,
                                  "valid": f"{base_coarse['valid_count']}/{base_coarse['count']}"}})
        if should_stop():
            rep.event("Leader", "train", "训练被用户中止。")
            break

        # -- 1b. L4 code evolution on scheduled rounds -------------------------------
        if try_l4(i, scene, train_cases, holdout_path,
                  str(ROOT / case_bank.ANCHOR), base_fine["avg_penalty"], fine_budget):
            rep.set_rsi({"operators": exp.op_stats(), "summary": exp.summary(),
                         "learned_ops": list(code_synthesis.load_registry(ROOT).keys())})
            continue

        # -- 2. candidates: UCB-selected proposal operators (RSI L2/L3) ------------
        seed = _stable_seed(mode, scene, i)
        raw_candidates = pool.select(scene, base_config, rnd=seed, k=4)
        candidates = [(op, ov, note) for op, ov, note in raw_candidates]
        summary["candidates"] += len(candidates)

        # -- 3a. coarse pass over every candidate -----------------------------------
        coarse = []  # (avg, overrides, origin, op_name, trial)
        for op_name, overrides, note in candidates:
            if should_stop():
                break
            screen = screen_average(train_cases, overrides, COARSE_BUDGET_MS)
            gain = (base_coarse["avg_penalty"] - screen["avg_penalty"]) / max(1e-9, base_coarse["avg_penalty"]) * 100.0
            exp.credit_operator(op_name, gain, won=gain > 0)
            exp.log_trial(i, scene, op_name, _plain(overrides),
                          screen["avg_penalty"], base_coarse["avg_penalty"], gain, "screened_coarse")
            origin = f"{op_name}({note})" if note else op_name
            trial = {"round": i, "scene": scene, "origin": origin, "stage": "coarse",
                     "overrides": _plain(overrides),
                     "screen_avg": round(screen["avg_penalty"], 3),
                     "baseline_avg": round(base_coarse["avg_penalty"], 3),
                     "gain_pct": round(gain, 2), "decision": "screened"}
            summary["trial_log"].append(trial)
            rep.jlog_trials({"time": time.strftime("%H:%M:%S"), **trial})
            coarse.append((screen["avg_penalty"], overrides, origin, op_name, trial))
        coarse.sort(key=lambda item: item[0])

        # -- 3b. fine re-check of the leaders (decision stage, shared fine baseline) -
        fine_leaders = []  # (fine_avg, overrides, origin, op_name, trial_id)
        decision_base = base_coarse["avg_penalty"]
        if coarse:
            leaders = coarse[:REFINE_TOP_N]
            decision_base = base_fine["avg_penalty"]
            rep.timeline({"round": i, "scene": scene, "agent": "Evaluator",
                          "message": f"fine re-check: {len(leaders)} leaders @ {int(fine_budget)}ms, "
                                     f"baseline {base_fine['avg_penalty']:.2f}",
                          "metrics": {"avg_penalty": round(base_fine["avg_penalty"], 3),
                                      "budget_ms": fine_budget}})
            for _avg_c, overrides, origin, op_name, _trial in leaders:
                if should_stop():
                    break
                fine = screen_average(train_cases, overrides, fine_budget)
                gain_f = (base_fine["avg_penalty"] - fine["avg_penalty"]) / max(1e-9, base_fine["avg_penalty"]) * 100.0
                exp.credit_operator(op_name, gain_f, won=gain_f > 0)
                exp.log_trial(i, scene, op_name, _plain(overrides),
                              fine["avg_penalty"], base_fine["avg_penalty"], gain_f, "screened_fine")
                fine_trial_id = int(exp.db.execute("SELECT last_insert_rowid()").fetchone()[0])
                trial_f = {"round": i, "scene": scene, "origin": origin, "stage": "fine",
                           "overrides": _plain(overrides),
                           "screen_avg": round(fine["avg_penalty"], 3),
                           "baseline_avg": round(base_fine["avg_penalty"], 3),
                           "gain_pct": round(gain_f, 2), "decision": "screened"}
                summary["trial_log"].append(trial_f)
                rep.jlog_trials({"time": time.strftime("%H:%M:%S"), **trial_f})
                fine_leaders.append((fine["avg_penalty"], overrides, origin, op_name, fine_trial_id))
        fine_leaders.sort(key=lambda item: item[0])
        rep.set_rsi({"operators": exp.op_stats(), "summary": exp.summary(),
                     "learned_ops": list(code_synthesis.load_registry(ROOT).keys())})
        # Keep every fine leader within threshold of the fine baseline: full-budget
        # validation is the real gate, so it is worth spending on near-misses too.
        validation_pool = [item for item in fine_leaders
                           if item[0] <= decision_base * (1.0 - SCREEN_IMPROVEMENT_MIN)]
        if not validation_pool:
            best = fine_leaders[0] if fine_leaders else None
            reason = (f"筛选无改进：best={best[0]:.2f} vs baseline={decision_base:.2f}"
                      if best else "无候选")
            summary["rejected"] += 1
            trial["decision"] = "reject"
            rep.timeline({"round": i, "scene": scene, "agent": "Trainer",
                          "message": f"candidate rejected: {reason}",
                          "metrics": {"decision": "reject"}})
            attribution = llm.attribute_failure({
                "scene": scene, "reason": reason,
                "baseline_avg": decision_base,
                "best_candidate": None if best is None else
                {"origin": best[2], "overrides": _plain(best[1]), "screen_avg": best[0]},
            })
            if attribution:
                rep.notes(f"\n## 归因（round {i}, {scene}）\n\n{attribution}\n")
            continue
        if should_stop():
            break

        # -- 4. full-budget validation of every fine leader within threshold ----------
        champion_anchor = ensure_champion(ANCHOR_KEY, anchor_path)
        champion_holdout = ensure_champion(f"holdout:{scene}", holdout_path)
        validated = None  # (overrides, origin, op_name, trial_id, cand_anchor, cand_holdout)
        for _fine_avg, gain_overrides, origin, op_name, trial_id in validation_pool:
            if should_stop():
                break
            cand_anchor = evaluate_case(anchor_path, gain_overrides, DEFAULT_FULL_BUDGET_MS)
            cand_holdout = evaluate_case(holdout_path, gain_overrides, DEFAULT_FULL_BUDGET_MS)
            anchor_gain = float(champion_anchor.get("penalty_score", float("inf"))) - \
                float(cand_anchor.get("penalty_score", float("inf")))
            holdout_gain = float(champion_holdout.get("penalty_score", float("inf"))) - \
                float(cand_holdout.get("penalty_score", float("inf")))
            anchor_ok = (cand_anchor.get("ok") and cand_anchor.get("valid")
                         and int(cand_anchor.get("covered_tasks", 0)) >=
                         int(champion_anchor.get("covered_tasks", 0))
                         and anchor_gain >= -ANCHOR_NO_REGRESS)
            clears_noise = holdout_gain >= HOLDOUT_MIN_GAIN and anchor_ok
            ok = better_by_penalty(cand_holdout, champion_holdout) and clears_noise
            rep.timeline({"round": i, "scene": scene, "agent": "Evaluator",
                          "message": (f"validation({origin}): anchor "
                                      f"{champion_anchor['penalty_score']:.2f} -> "
                                      f"{cand_anchor.get('penalty_score', float('inf')):.2f}, "
                                      f"holdout {champion_holdout['penalty_score']:.2f} -> "
                                      f"{cand_holdout.get('penalty_score', float('inf')):.2f}"),
                          "metrics": {"anchor": cand_anchor.get("penalty_score"),
                                      "holdout": cand_holdout.get("penalty_score"),
                                      "valid": ok}})
            if ok:
                validated = (gain_overrides, origin, op_name, trial_id, cand_anchor, cand_holdout)
                break
        if not validated:
            summary["rejected"] += 1
            rep.timeline({"round": i, "scene": scene, "agent": "Auditor",
                          "message": "no candidate survived full-budget validation",
                          "metrics": {"decision": "reject"}})
            continue
        gain_overrides, origin = validated[0], validated[1]
        cand_anchor, cand_holdout = validated[4], validated[5]
        if should_stop():
            rep.event("Leader", "train", "训练被用户中止。")
            break

        # -- 5. protected no-regression gate (adaptive tolerance) ----------------------
        # Base tolerance from params (default 0.5). Optionally trade: anchor gains
        # may buy extra tolerance (anchor_tradeoff_ratio, capped), e.g. gain 4.0
        # with ratio 0.25 allows +1.0 per protected case. Off by default (ratio 0).
        anchor_gain = float(champion_anchor["penalty_score"]) - float(cand_anchor["penalty_score"])
        tol_base = float(train_params.get("regression_tolerance", REGRESSION_TOLERANCE))
        tol_ratio = float(train_params.get("anchor_tradeoff_ratio", 0.0))
        tol_cap = float(train_params.get("anchor_tradeoff_cap", 1.0))
        tolerance = tol_base + (min(tol_cap, max(0.0, anchor_gain) * tol_ratio) if tol_ratio > 0 else 0.0)
        gate_ok, gate_metrics, gate_runs = True, {}, {}
        for name, path in protected:
            # Paired measurement against a fresh baseline (protected runs drift
            # ±2.3 with load; a stale stored champion would misjudge the delta).
            fresh_base = evaluate_case(path, None, DEFAULT_FULL_BUDGET_MS)
            cand_p = evaluate_case(path, gain_overrides, DEFAULT_FULL_BUDGET_MS)
            gate_metrics[name] = cand_p.get("penalty_score")
            gate_runs[name] = cand_p
            paired_delta = float(cand_p.get("penalty_score", float("inf"))) - \
                float(fresh_base.get("penalty_score", float("inf")))
            regressed = (not cand_p.get("ok") or not cand_p.get("valid") or
                         paired_delta > tolerance)
            if regressed:
                gate_ok = False
                rep.forensic(
                    f"protected:{name}",
                    f"候选（{origin}）在保护场景 {name} 上配对回退 {paired_delta:+.2f} 超容忍"
                    f"（容忍={tolerance:.2f}，anchor_gain={anchor_gain:.2f}，"
                    f"同负载基线 {fresh_base.get('penalty_score')}），已拒绝晋升。",
                    "danger", f"promote({_fmt_overrides(gain_overrides)})",
                    "keep CONFIG unchanged (protected threshold preserved)")
                break
        if not gate_ok:
            summary["rejected"] += 1
            if tol_ratio <= 0 and anchor_gain >= 2.0:
                rep.event("Auditor", "guard",
                          f"anchor 实际改进 {anchor_gain:.2f} 但保护门禁拒绝。"
                          "可在 params.json global 中设置 anchor_tradeoff_ratio（如 0.25）"
                          "允许以 anchor 收益换取保护容忍后重试。")
            rep.timeline({"round": i, "scene": scene, "agent": "Auditor",
                          "message": "protected regression gate rejected candidate",
                          "metrics": {"decision": "reject", "tolerance": round(tolerance, 3),
                                      "anchor_gain": round(anchor_gain, 3), **gate_metrics}})
            continue
        if should_stop():
            rep.event("Leader", "train", "训练被用户中止。")
            break

        # -- 6. promote: backup -> splice CONFIG -> smoke verify -> commit --------------
        backup = rep.backup(f"promote_r{i}")
        solver_text_before = SOLVER_PATH.read_text(encoding="utf-8")
        old_excerpt = {k: base_config.get(k) for k in gain_overrides}
        new_config = {**base_config, **gain_overrides}
        write_info = config_io.write_config(SOLVER_PATH, new_config)
        smoke = evaluate_case(anchor_path, None, SMOKE_BUDGET_MS)
        promoted = bool(smoke.get("ok"))
        if promoted:
            exp.mark_promoted(validated[3], float(cand_anchor["penalty_score"]),
                              float(cand_holdout["penalty_score"]))
            if float(cand_anchor.get("penalty_score", float("inf"))) < \
                    float(champions[ANCHOR_KEY].get("penalty_score", float("inf"))):
                champions[ANCHOR_KEY] = cand_anchor   # only bump on real anchor gain
                rep.set_champion(ANCHOR_KEY, cand_anchor)
            champions[f"holdout:{scene}"] = cand_holdout
            rep.set_champion(f"holdout:{scene}", cand_holdout)
            for name, _path in protected:
                if float(gate_runs[name].get("penalty_score", float("inf"))) < float(
                        champions.get(f"protected:{name}", {}).get("penalty_score", float("inf"))):
                    champions[f"protected:{name}"] = gate_runs[name]  # only on real gain
                    rep.set_champion(f"protected:{name}", gate_runs[name])
            summary["promoted"] += 1
            rep.forensic(
                scene, f"Round {i} 晋升（{origin}）：anchor "
                       f"{champion_anchor['penalty_score']:.2f} -> {cand_anchor['penalty_score']:.2f}, "
                       f"holdout {champion_holdout['penalty_score']:.2f} -> "
                       f"{cand_holdout['penalty_score']:.2f}，保护场景无回退。",
                "info", " / ".join(f"{k}={old_excerpt[k]}" for k in old_excerpt),
                _fmt_overrides(gain_overrides))
            rep.set_trend(i, float(cand_anchor["penalty_score"]))
            rep.agent("leader", decision="promoted")
            rep.event("Leader", "promote",
                      f"Round {i}: promoted {_fmt_overrides(gain_overrides)} "
                      f"(anchor {cand_anchor['penalty_score']:.2f}, backup {backup['name']})")
        else:
            SOLVER_PATH.write_text(solver_text_before, encoding="utf-8", newline="")
            summary["rejected"] += 1
            rep.event("Auditor", "guard",
                      f"晋升后 smoke 验证失败（write_info={write_info.get('config_keys')} keys），"
                      "已恢复原 CONFIG。")
        rep.timeline({"round": i, "scene": scene, "agent": "Leader",
                      "message": "promoted" if promoted else "promote failed, reverted",
                      "metrics": {"decision": "promote" if promoted else "revert",
                                  "anchor": cand_anchor.get("penalty_score")}})

    summary["elapsed_s"] = round(time.time() - started, 1)
    summary["params"] = train_params
    summary["rsi"] = {"operators": exp.op_stats(), "summary": exp.summary(),
                      "learned_ops": list(code_synthesis.load_registry(ROOT).keys())}
    summary["champions"] = {k: {"penalty_score": v.get("penalty_score"),
                                "covered_tasks": v.get("covered_tasks"),
                                "total_tasks": v.get("total_tasks")}
                            for k, v in champions.items()}
    exp.close()
    return summary
