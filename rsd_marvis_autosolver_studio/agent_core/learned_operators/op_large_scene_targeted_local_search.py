def mutate_config(config, scene, rng):
    overrides = {}
    if scene == "large":
        local_budget = config.get("local_search_budget_ms", 0.0)
        replace_tasks = config.get("max_exact_replace_tasks", 4)
        overrides["local_search_budget_ms"] = min(4000.0, local_budget + 750.0)
        overrides["max_exact_replace_tasks"] = int(min(14, replace_tasks + 3))
    return overrides