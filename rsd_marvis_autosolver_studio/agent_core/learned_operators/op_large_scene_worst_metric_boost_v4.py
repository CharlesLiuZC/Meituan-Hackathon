def mutate_config(config, scene, rng):
    overrides = {}
    if scene == 'large':
        ls = config.get('local_search_budget_ms', 1000.0)
        overrides['local_search_budget_ms'] = round(min(4000.0, max(0.0, ls * 1.35 + 400.0)), 0)
        preview = config.get('normal_preview_scan_per_primary', 20)
        overrides['normal_preview_scan_per_primary'] = min(60, max(6, preview + 12))
        topo_k = config.get('normal_topology_top_k', 8)
        overrides['normal_topology_top_k'] = min(16, max(2, topo_k + 3))
        topo_limit = config.get('normal_topology_generated_limit', 14)
        overrides['normal_topology_generated_limit'] = min(30, max(4, topo_limit + 6))
        pair_k = config.get('pair_top_k', 30)
        overrides['pair_top_k'] = min(80, max(8, pair_k + 18))
        triple_k = config.get('triple_top_k', 20)
        overrides['triple_top_k'] = min(60, max(6, triple_k + 12))
        if not config.get('try_triples', False):
            overrides['try_triples'] = True
        auto_budget = config.get('auto_strategy_budget_ms', 300.0)
        if auto_budget > 420.0:
            overrides['auto_strategy_budget_ms'] = 420.0
        elif auto_budget < 240.0:
            overrides['auto_strategy_budget_ms'] = 240.0
        exact = config.get('max_exact_replace_tasks', 8)
        if exact < 10:
            overrides['max_exact_replace_tasks'] = min(14, exact + 2)
    else:
        backup = config.get('normal_preview_backup_cap', 3)
        overrides['normal_preview_backup_cap'] = min(6, backup + 1)
    return overrides