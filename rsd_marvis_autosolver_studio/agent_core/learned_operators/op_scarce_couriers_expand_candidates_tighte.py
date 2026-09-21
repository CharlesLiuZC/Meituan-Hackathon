def mutate_config(config, scene, rng):
    if scene == 'scarce_couriers':
        pair_top_k = int(config.get('pair_top_k', 40))
        triple_top_k = int(config.get('triple_top_k', 30))
        max_exact_replace_tasks = int(config.get('max_exact_replace_tasks', 8))
        max_candidates_per_mask = int(config.get('max_candidates_per_mask', 30))
        special_max_candidates_per_mask = int(config.get('special_max_candidates_per_mask', 6))
        safety_margin_ms = float(config.get('safety_margin_ms', 500.0))
        return {
            'pair_top_k': min(80, pair_top_k + 8 + rng.randrange(6)),
            'triple_top_k': min(60, triple_top_k + 5 + rng.randrange(5)),
            'max_exact_replace_tasks': min(14, max_exact_replace_tasks + 1 + rng.randrange(3)),
            'max_candidates_per_mask': min(60, max_candidates_per_mask + 6 + rng.randrange(8)),
            'special_max_candidates_per_mask': min(12, special_max_candidates_per_mask + 1 + rng.randrange(3)),
            'safety_margin_ms': round(max(100.0, safety_margin_ms - 40.0 - rng.uniform(0.0, 60.0)), 2)
        }
    return {}