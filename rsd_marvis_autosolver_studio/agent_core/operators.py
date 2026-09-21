"""Proposal-operator pool with UCB1 selection: the agent improves its own
improvement policy (RSI level 2).

Every candidate CONFIG proposal is produced by a named operator. Operators that
historically produce screening wins on a scene get fired more often; new or
under-tried operators keep an exploration bonus. The pool also contains
operators the agent wrote for itself (code_synthesis) -- level 3.
"""
from __future__ import annotations

import random
from pathlib import Path

from . import code_synthesis, llm, mutations

BUILTIN_OPS = [
    ("random_mutate", "builtin"),
    ("strategy_jitter", "builtin"),
    ("strategy_evolution", "builtin"),
    ("crossover", "builtin"),
    ("leverage_guided", "builtin"),
    ("llm_propose", "llm"),
    ("llm_strategies", "llm"),
]


class OperatorPool:
    def __init__(self, exp, root: Path):
        self.exp = exp
        self.root = Path(root)
        self.last_note = ""  # guard/filter notes from the most recent firing
        for name, kind in BUILTIN_OPS:
            exp.register_operator(name, kind, 0)

    # -- builtin operator implementations ----------------------------------------
    def _op_random_mutate(self, scene, config, rng, rnd) -> dict:
        return mutations.mutate(config, scene, rng, n_keys=2)

    def _op_strategy_jitter(self, scene, config, rng, rnd) -> dict:
        if scene not in ("medium", "large", "high_noise"):
            return {}
        return mutations.jitter_strategies(config, rng)

    def _op_strategy_evolution(self, scene, config, rng, rnd) -> dict:
        """Joint multi-weight perturbation: evolve 2-4 weights across tuples at
        ±40% magnitude -- a far larger ordering-space step than single jitter."""
        strategies = config.get("strategies")
        if not isinstance(strategies, list) or not strategies:
            return {}
        new = [list(s) for s in strategies]
        n_mut = rng.randint(2, 4)
        for _ in range(n_mut):
            si = rng.randrange(len(new))
            wi = rng.randrange(len(new[si]) - 1)  # keep bundle_first flag stable
            old = float(new[si][wi])
            scale = rng.uniform(0.6, 1.4) if old > 1e-6 else rng.uniform(-0.15, 0.15)
            new[si][wi] = round(old * scale, 4)
        return {"strategies": [tuple(s) for s in new]}

    def _op_llm_strategies(self, scene, config, rng, rnd) -> dict:
        ok, _ = llm.available()
        if not ok or rnd % 3 != 0:
            return {}
        context = [dict(r) for r in self.exp.db.execute(
            "SELECT round, scene, op, gain_pct, decision FROM trials"
            " ORDER BY id DESC LIMIT 6").fetchall()]
        proposal = llm.propose_strategies(scene, config.get("strategies", []), context)
        if not proposal:
            return {}
        raw, rationale = proposal
        accepted, rejected = mutations.validate_overrides(config, scene, {"strategies": raw})
        if rejected:
            self.last_note = f"LLM 策略提案被白名单过滤：{rejected}"
            return {}
        self.last_note = f"llm-strategies: {rationale}"
        return accepted

    def _op_crossover(self, scene, config, rng, rnd) -> dict:
        wins = self.exp.winning_overrides(scene, k=3)
        if not wins:
            return {}
        merged = {}
        for w in rng.sample(wins, min(2, len(wins))):
            for key, value in w.items():
                if key in config and key not in merged and rng.random() < 0.7:
                    merged[key] = value
        return merged

    def _op_leverage_guided(self, scene, config, rng, rnd) -> dict:
        keys = self.exp.leverage_keys(scene, k=2)
        if not keys:
            return {}
        return mutations.mutate(config, scene, rng, n_keys=2, keys=keys)

    def _op_llm_propose(self, scene, config, rng, rnd) -> dict:
        ok, _ = llm.available()
        if not ok or rnd % 2 == 0:
            return {}
        context = [dict(r) for r in self.exp.db.execute(
            "SELECT round, scene, op, gain_pct, decision FROM trials"
            " ORDER BY id DESC LIMIT 6").fetchall()]
        proposal = llm.propose_overrides(
            scene, mutations.SCENE_KEYS.get(scene, []), config, context)
        if not proposal:
            return {}
        raw, rationale = proposal
        accepted, rejected = mutations.validate_overrides(config, scene, raw)
        if rejected:
            self.last_note = f"LLM 提案被白名单过滤：{rejected}"
        self.last_note = f"llm: {rationale}" if accepted else self.last_note
        return accepted

    # -- dispatch ------------------------------------------------------------------
    def _fire(self, name: str, scene: str, config: dict,
              rng: random.Random, rnd: int) -> dict:
        """Returns raw overrides. Learned ops run in a subprocess sandbox."""
        self.last_note = ""
        if name == "random_mutate":
            return self._op_random_mutate(scene, config, rng, rnd)
        if name == "strategy_jitter":
            return self._op_strategy_jitter(scene, config, rng, rnd)
        if name == "strategy_evolution":
            return self._op_strategy_evolution(scene, config, rng, rnd)
        if name == "llm_strategies":
            return self._op_llm_strategies(scene, config, rng, rnd)
        if name == "crossover":
            return self._op_crossover(scene, config, rng, rnd)
        if name == "leverage_guided":
            return self._op_leverage_guided(scene, config, rng, rnd)
        if name == "llm_propose":
            return self._op_llm_propose(scene, config, rng, rnd)
        learned = code_synthesis.load_registry(self.root).get(name)
        if learned:
            ok, overrides, err = code_synthesis.sandbox_run(
                self.root / "agent_core" / "learned_operators" / learned["file"],
                config, scene, rng.randrange(1 << 30))
            if not ok:
                self.last_note = f"learned op failed: {err}"
                return {}
            return overrides
        self.last_note = "unknown op"
        return {}

    def select(self, scene: str, config: dict, rnd: int, k: int = 4) -> list[tuple[str, dict, str]]:
        """UCB-ranked operator firing -> [(op_name, validated_overrides, note)].

        llm_propose (on eligible rounds) and learned operators get priority
        slots: without this they starve behind UCB-decayed builtins and the
        meta loop never gets a chance to prove its operators.
        """
        stats = self.exp.op_stats()
        ok_llm, _ = llm.available()
        learned = code_synthesis.load_registry(self.root)
        priority = []
        if ok_llm and rnd % 2 == 1:
            priority.append("llm_propose")
        if ok_llm and rnd % 3 == 0:
            priority.append("llm_strategies")
        priority += [n for n in learned if n in stats]
        pool_owned = {name for name, _kind in BUILTIN_OPS}
        ranked = sorted(((n, s) for n, s in stats.items()
                         if n in pool_owned or n in learned),
                        key=lambda kv: kv[1]["ucb"], reverse=True)
        order = priority + [name for name, _ in ranked if name not in priority]
        rng = random.Random(rnd * 7919 + (abs(hash(scene)) % 100000))
        candidates = []
        for name in order:
            if len(candidates) >= k:
                break
            if name == "llm_propose" and (not ok_llm or rnd % 2 == 0):
                continue
            if name == "llm_strategies" and (not ok_llm or rnd % 3 != 0):
                continue
            raw = self._fire(name, scene, config, rng, rnd)
            if not raw:
                continue
            accepted, rejected = mutations.validate_overrides(config, scene, raw)
            note = self.last_note
            if rejected:
                note = (note + f" [filtered: {len(rejected)}]").strip()
            if accepted:
                candidates.append((name, accepted, note))
        return candidates
