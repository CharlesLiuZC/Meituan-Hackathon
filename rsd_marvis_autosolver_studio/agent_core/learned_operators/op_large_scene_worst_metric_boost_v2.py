def mutate_config(config, scene, rng):
    if scene != 'large':
        return {}
    ls = config.get('local_search_budget_ms', 2000.0)
    exact = config.get('max_exact_replace_tasks', 8)
    top_k = config.get('normal_topology_top_k', 8)
    generated = config.get('normal_topology_generated_limit', 16)
    scan = config.get('normal_preview_scan_per_primary', 30)
    pair_k = config.get('pair_top_k', 40)
    triple_k = config.get('triple_top_k', 30)
    if ls >= 2400.0 or exact <= 5:
        return {
            'local_search_budget_ms': round(max(0.0, ls * 0.5), 1),
            'normal_topology_top_k': min(16, top_k + 4),
            'normal_topology_generated_limit': min(30, generated + 8),
            'normal_preview_scan_per_primary': min(60, scan + 12),
            'pair_top_k': min(80, pair_k + 16),
            'triple_top_k': min(60, triple_k + 12),
            'try_triples': True,
            'max_exact_replace_tasks': min(14, exact + 3)
        }
    return {
        'local_search_budget_ms': round(min(4000.0, ls * 1.15), 1),
        'normal_topology_top_k': max(2, top_k - 1),
        'normal_topology_generated_limit': max(4, generated - 3),
        'normal_preview_scan_per_primary': max(6, scan - 6),
        'pair_top_k': max(8, pair_k - 8),
        'triple_top_k': max(6, triple_k - 6),
        'try_triples': False,
        'max_exact_replace_tasks': max(4, exact - 2)
    }