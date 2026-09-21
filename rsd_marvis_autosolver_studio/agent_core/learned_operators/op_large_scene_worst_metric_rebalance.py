def mutate_config(config, scene, rng):
    overrides = {}
    if scene == 'large':
        current_local = config.get('local_search_budget_ms', 800.0)
        if current_local > 2800.0:
            overrides['local_search_budget_ms'] = round(rng.uniform(1400.0, 2000.0), 0)
        else:
            overrides['local_search_budget_ms'] = round(rng.uniform(1800.0, 2600.0), 0)
        overrides['normal_topology_generated_limit'] = int(rng.choice([14, 18, 22, 26]))
        overrides['pair_top_k'] = int(rng.choice([40, 48, 56, 64]))
        overrides['triple_top_k'] = int(rng.choice([24, 30, 36]))
        overrides['try_triples'] = True
    elif scene == 'high_noise':
        overrides['normal_preview_backup_cap'] = int(rng.choice([2, 3, 4]))
        overrides['normal_preview_scan_per_primary'] = int(rng.choice([10, 14, 18]))
        overrides['pair_top_k'] = int(rng.choice([20, 28, 36]))
        overrides['try_triples'] = False
    else:
        overrides['normal_topology_generated_limit'] = int(rng.choice([10, 12, 14]))
        overrides['pair_top_k'] = int(rng.choice([28, 36, 44]))
        overrides['try_triples'] = bool(rng.getrandbits(1))
    return overrides