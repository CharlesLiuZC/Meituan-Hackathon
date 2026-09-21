def mutate_config(config, scene, rng):
    if scene != "large":
        return {}
    local = config.get("local_search_budget_ms", 2000.0)
    backup = config.get("normal_preview_backup_cap", 3)
    scan = config.get("normal_preview_scan_per_primary", 30)
    pair = config.get("pair_top_k", 40)
    triple = config.get("triple_top_k", 30)
    exact = config.get("max_exact_replace_tasks", 8)
    top_k = config.get("normal_topology_top_k", 8)
    gen_limit = config.get("normal_topology_generated_limit", 12)
    try_triples = config.get("try_triples", False)

    if backup < 4:
        return {"normal_preview_backup_cap": min(6, backup + 1)}
    if local < 3000.0:
        return {"local_search_budget_ms": min(4000.0, local + 600.0)}
    if scan < 42:
        return {"normal_preview_scan_per_primary": min(60, scan + 10)}
    if pair < 60:
        return {"pair_top_k": min(80, pair + 12)}
    if try_triples and triple < 45:
        return {"triple_top_k": min(60, triple + 9)}
    if exact < 11:
        return {"max_exact_replace_tasks": min(14, exact + 2)}
    if top_k < 13:
        return {"normal_topology_top_k": min(16, top_k + 2)}
    if gen_limit < 24:
        return {"normal_topology_generated_limit": min(30, gen_limit + 4)}
    return {}