def mutate_config(config, scene, rng):
    if scene != 'low_willingness':
        return {}
    safety = config.get('safety_margin_ms', 600.0)
    pair_top_k = config.get('pair_top_k', 40)
    triple_top_k = config.get('triple_top_k', 30)
    try_triples = config.get('try_triples', True)
    u = rng.random()
    changes = {}
    slack_ratio = (900.0 - safety) / 800.0
    safety_increase = 0.10 + 0.10 * u + 0.15 * slack_ratio
    new_safety = min(900.0, max(100.0, round(safety * (1.0 + safety_increase), 0)))
    if new_safety > safety:
        changes['safety_margin_ms'] = new_safety
    shrink = 1.0 - (0.10 + 0.15 * u)
    new_pair = min(80, max(8, int(round(pair_top_k * shrink))))
    if new_pair < pair_top_k:
        changes['pair_top_k'] = new_pair
    new_triple = min(60, max(6, int(round(triple_top_k * shrink))))
    if new_triple < triple_top_k:
        changes['triple_top_k'] = new_triple
    if try_triples and u < 0.55:
        changes['try_triples'] = False
    return changes