def mutate_config(config, scene, rng):
    if scene != 'large':
        return {}
    local_budget = config.get('local_search_budget_ms', 1800.0)
    preview_scan = config.get('normal_preview_scan_per_primary', 24)
    topo_k = config.get('normal_topology_top_k', 8)
    topo_limit = config.get('normal_topology_generated_limit', 12)
    pair_k = config.get('pair_top_k', 32)
    triple_k = config.get('triple_top_k', 24)
    exact_replace = config.get('max_exact_replace_tasks', 8)
    return {
        'local_search_budget_ms': min(4000.0, max(2200.0, local_budget + 900.0)),
        'normal_preview_scan_per_primary': min(60, max(36, preview_scan + 12)),
        'normal_topology_top_k': min(16, max(10, topo_k + 3)),
        'normal_topology_generated_limit': min(30, max(18, topo_limit + 6)),
        'pair_top_k': min(80, max(44, pair_k + 16)),
        'triple_top_k': min(60, max(30, triple_k + 12)),
        'try_triples': True,
        'max_exact_replace_tasks': min(14, max(8, exact_replace + 2))
    }