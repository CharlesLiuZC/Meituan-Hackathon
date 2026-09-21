"""agent_core: real evaluation & training loop for RSD-Marvis AutoSolver Studio.

Replaces the V5 hardfix "fake training" (hardcoded gains + sleep) with:
  evaluator     -- official-like scorer (validity, coverage, penalty)
  solver_runner -- subprocess-isolated solver execution with CONFIG overrides
  case_bank     -- deterministic scene-true train/holdout/protected cases
  mutations     -- whitelisted CONFIG mutation proposals
  llm           -- DeepSeek structured proposals & failure attribution (optional)
  trainer       -- one-click training: screen -> validate -> gate -> promote/rollback
"""
