def mutate_config(config, scene, rng):
    overrides = {}
    if scene == "large":
        local = float(config.get("local_search_budget_ms", 0.0))
        if local < 3000.0:
            overrides["local_search_budget_ms"] = min(4000.0, round(local * 1.22 + 100.0, 1))
        else:
            auto = float(config.get("auto_strategy_budget_ms", 120.0))
            overrides["auto_strategy_budget_ms"] = min(600.0, round(auto * 1.22 + 40.0, 1))
        key = rng.choice(["normal_preview_scan_per_primary", "normal_preview_backup_cap", "normal_topology_top_k", "normal_topology_generated_limit", "pair_top_k", "triple_top_k"])
        if key == "normal_preview_scan_per_primary":
            val = int(config.get(key, 6))
            overrides[key] = min(60, val + rng.randrange(8, 18))
        elif key == "normal_preview_backup_cap":
            val = int(config.get(key, 1))
            overrides[key] = min(6, val + rng.randrange(1, 3))
        elif key == "normal_topology_top_k":
            val = int(config.get(key, 2))
            overrides[key] = min(16, val + rng.randrange(3, 7))
        elif key == "normal_topology_generated_limit":
            val = int(config.get(key, 4))
            overrides[key] = min(30, val + rng.randrange(5, 10))
        elif key == "pair_top_k":
            val = int(config.get(key, 8))
            overrides[key] = min(80, val + rng.randrange(10, 22))
        elif key == "triple_top_k":
            val = int(config.get(key, 6))
            overrides[key] = min(60, val + rng.randrange(8, 18))
    elif scene == "high_noise":
        key = rng.choice(["max_exact_replace_tasks", "normal_preview_backup_cap"])
        if key == "max_exact_replace_tasks":
            val = int(config.get(key, 4))
            overrides[key] = min(14, val + rng.randrange(2, 5))
        else:
            val = int(config.get(key, 1))
            overrides[key] = min(6, val + rng.randrange(1, 3))
    else:
        key = rng.choice(["pair_top_k", "triple_top_k"])
        if key == "pair_top_k":
            val = int(config.get(key, 8))
            overrides[key] = min(80, val + rng.randrange(6, 16))
        else:
            val = int(config.get(key, 6))
            overrides[key] = min(60, val + rng.randrange(5, 12))
    return overrides