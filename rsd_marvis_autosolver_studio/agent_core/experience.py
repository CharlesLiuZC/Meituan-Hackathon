"""Persistent experience memory for the self-improving loop (stdlib sqlite3).

Three consumers feed on this and each other through it:
  L1  solver improvement   -- promoted CONFIGs land in solver.py (trainer)
  L2  policy improvement   -- UCB bandit over proposal operators (operators.py)
  L3  operator synthesis   -- LLM writes NEW operator code for itself (code_synthesis)

Every screened candidate is logged with its origin operator, so the agent can
learn which kinds of proposals actually produce gains on which scenes.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA_VERSION = 1


class Experience:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'")
        if cur.fetchone() is None:
            self._create()
            return
        version = self.db.execute("SELECT value FROM meta WHERE key='version'").fetchone()
        if not version or int(version[0]) != SCHEMA_VERSION:
            self._create()  # recreate on schema change; backups exist elsewhere

    def _create(self) -> None:
        self.db.executescript("""
            DROP TABLE IF EXISTS meta;
            DROP TABLE IF EXISTS trials;
            DROP TABLE IF EXISTS operators;
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE trials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL, round INTEGER, scene TEXT, op TEXT,
                overrides_json TEXT, screen_avg REAL, baseline_avg REAL,
                gain_pct REAL, decision TEXT,
                anchor_penalty REAL, holdout_penalty REAL);
            CREATE TABLE operators (
                name TEXT PRIMARY KEY, kind TEXT, born_round INTEGER,
                uses INTEGER DEFAULT 0, wins INTEGER DEFAULT 0,
                gain_sum REAL DEFAULT 0.0, retired INTEGER DEFAULT 0);
        """)
        self.db.execute("INSERT INTO meta VALUES ('version', ?)", (str(SCHEMA_VERSION),))
        self.db.commit()

    # -- trials -----------------------------------------------------------------
    def log_trial(self, rnd: int, scene: str, op: str, overrides: dict,
                  screen_avg: float, baseline_avg: float, gain_pct: float,
                  decision: str) -> int:
        cur = self.db.execute(
            "INSERT INTO trials (ts, round, scene, op, overrides_json, screen_avg,"
            " baseline_avg, gain_pct, decision) VALUES (?,?,?,?,?,?,?,?,?)",
            (time.time(), rnd, scene, op, json.dumps(overrides, ensure_ascii=False),
             screen_avg, baseline_avg, gain_pct, decision))
        self.db.commit()
        return cur.lastrowid

    def mark_promoted(self, trial_id: int, anchor_penalty: float, holdout_penalty: float) -> None:
        self.db.execute("UPDATE trials SET decision='promoted', anchor_penalty=?, holdout_penalty=?"
                        " WHERE id=?", (anchor_penalty, holdout_penalty, trial_id))
        self.db.commit()

    def winning_overrides(self, scene: str, k: int = 3) -> list[dict]:
        """Best screened overrides for a scene (crossover material)."""
        rows = self.db.execute(
            "SELECT overrides_json, gain_pct FROM trials WHERE scene=? AND gain_pct>0"
            " ORDER BY gain_pct DESC LIMIT ?", (scene, k)).fetchall()
        return [json.loads(r["overrides_json"]) for r in rows]

    # -- operators ----------------------------------------------------------------
    def register_operator(self, name: str, kind: str, born_round: int) -> None:
        self.db.execute("INSERT OR IGNORE INTO operators (name, kind, born_round) VALUES (?,?,?)",
                        (name, kind, born_round))

    def credit_operator(self, name: str, gain_pct: float, won: bool) -> None:
        # Clamp to a sane band: an invalid run screens as inf penalty -> gain
        # -inf, which would permanently poison gain_sum/avg/UCB for the operator.
        if gain_pct != gain_pct or gain_pct in (float("inf"), float("-inf")):
            gain_pct = -50.0
        gain_pct = max(-50.0, min(50.0, float(gain_pct)))
        self.db.execute(
            "UPDATE operators SET uses=uses+1, wins=wins+?, gain_sum=gain_sum+? WHERE name=?",
            (1 if won else 0, gain_pct, name))
        self.db.commit()

    def repair_operator_stats(self, name: str) -> None:
        """Recompute a poisoned operator's sums from its bounded trials."""
        row = self.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(gain_pct), 0) FROM trials WHERE op=?",
            (name,)).fetchone()
        uses, bounded_sum = int(row[0]), 0.0
        for g in (r[0] for r in self.db.execute(
                "SELECT gain_pct FROM trials WHERE op=?", (name,)).fetchall()):
            if g is None or g != g or g in (float("inf"), float("-inf")):
                g = -50.0
            bounded_sum += max(-50.0, min(50.0, float(g)))
        wins = int(self.db.execute(
            "SELECT COUNT(*) FROM trials WHERE op=? AND gain_pct>0", (name,)).fetchone()[0])
        self.db.execute(
            "UPDATE operators SET uses=?, wins=?, gain_sum=? WHERE name=?",
            (uses, wins, bounded_sum, name))
        self.db.commit()

    def retire_operator(self, name: str) -> None:
        self.db.execute("UPDATE operators SET retired=1 WHERE name=?", (name,))
        self.db.commit()

    def active_operators(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT name, kind, born_round, uses, wins, gain_sum FROM operators"
            " WHERE retired=0 ORDER BY born_round").fetchall()
        return [dict(r) for r in rows]

    def op_stats(self, c: float = 0.35, floor: float = 0.5) -> dict:
        """UCB1-style stats; operators with no history get an exploration bonus."""
        stats = {}
        for r in self.active_operators():
            uses, wins = max(1, r["uses"]), r["wins"]
            avg_gain = r["gain_sum"] / uses
            exploit = avg_gain / 100.0            # gain_pct is a percentage
            explore = c * ((2.0 * sum(s["uses"] for s in
                          self.active_operators()) / uses) ** 0.5) if r["uses"] else floor
            stats[r["name"]] = {"kind": r["kind"], "uses": r["uses"], "wins": wins,
                                "win_rate": round(wins / uses, 3),
                                "avg_gain_pct": round(avg_gain, 2),
                                "ucb": round(exploit + explore, 3),
                                "born_round": r["born_round"]}
        return stats

    # -- key leverage analysis ------------------------------------------------------
    def leverage_keys(self, scene: str, k: int = 3) -> list[str]:
        """CONFIG keys that appear disproportionately in winning trials of a scene."""
        rows = self.db.execute(
            "SELECT overrides_json, decision FROM trials WHERE scene=? AND gain_pct>0",
            (scene,)).fetchall()
        if len(rows) < 2:
            return []
        counts: dict[str, int] = {}
        for r in rows:
            for key in json.loads(r["overrides_json"]):
                counts[key] = counts.get(key, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        return [key for key, _ in ranked[:k]]

    def summary(self) -> dict:
        n = self.db.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
        promoted = self.db.execute(
            "SELECT COUNT(*) FROM trials WHERE decision='promoted'").fetchone()[0]
        best = self.db.execute(
            "SELECT scene, op, gain_pct, overrides_json FROM trials"
            " WHERE gain_pct IS NOT NULL ORDER BY gain_pct DESC LIMIT 1").fetchone()
        return {
            "trials": n, "promoted": promoted,
            "operators": len(self.active_operators()),
            "best_screen": {"scene": best["scene"], "op": best["op"],
                            "gain_pct": round(best["gain_pct"], 2)} if best else None,
        }

    def close(self) -> None:
        self.db.close()
