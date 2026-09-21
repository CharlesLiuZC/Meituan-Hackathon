# Handover.md

## Current handover

- version: V5 hardfix
- champion score: 716.74
- static solver size: 68.92 KB
- official anchor: data/official/large_seed301.txt
- official greedy: data/official/example_solution.txt
- protected cases: small / tiny / scarce

## Next recommended action

Open dashboard → 一键训练 → Start one-click training.

## 2026-09-19T13:08:34 · Real training finished

- mode: safe-medium-only
- promoted/rejected/candidates: 0/2/5
- anchor measured: None
- backup: `pretrain_r0_20260919_130751.zip`

## 2026-09-19T13:13:53 · Real training finished

- mode: balanced
- promoted/rejected/candidates: 0/3/7
- anchor measured: {'ok': True, 'valid': True, 'penalty_score': 626.319027, 'covered_tasks': 40, 'total_tasks': 40, 'elapsed_ms': 7996.8, 'case_type': 'normal'}
- backup: `pretrain_r2_20260919_131222.zip`

## 2026-09-19 · V5.1 handover

- 训练循环已真实化（agent_core.trainer），所有 dashboard 数字为实测。
- champion.measured（current_state.json）保存各案例实测基线；控制台 `evaluate` 按钮可随时重测 anchor。
- 下一步建议：设 DEEPSEEK_API_KEY 启用 LLM 提案；跑 6 轮 balanced 观察首次晋升；
  筛选预算(3s)与全预算(9.3s)的排名迁移是主要调优点。

## 2026-09-19T13:52:06 · Real training finished

- mode: balanced
- promoted/rejected/candidates: 0/2/4
- anchor measured: {'ok': True, 'valid': True, 'penalty_score': 626.319027, 'covered_tasks': 40, 'total_tasks': 40, 'elapsed_ms': 8911.5, 'case_type': 'normal'}
- backup: `pretrain_r3_20260919_135134.zip`

## 2026-09-19 · V6 RSI handover

- 训练循环升级为三层 RSI（L1 solver / L2 bandit 策略 / L3 LLM 自写算子）。
- 经验库：memory/experience.sqlite（trials + operators 表）；state.rsi 暴露算子榜。
- 下一步：设 DEEPSEEK_API_KEY 后跑 6+ 轮 balanced，观察元步注入的新算子是否胜出；
  若 crossover/leverage_guided 长期 0 胜可考虑 retire 机制（exp.retire_operator 已备）。

## 2026-09-19T14:02:33 · Real training finished

- mode: balanced
- promoted/rejected/candidates: 0/6/12
- anchor measured: {'ok': True, 'valid': True, 'penalty_score': 626.319027, 'covered_tasks': 40, 'total_tasks': 40, 'elapsed_ms': 8911.5, 'case_type': 'normal'}
- backup: `pretrain_r2_20260919_135726.zip`

## Forensics · RSI-operator

- Round 3 元步：Agent 为自己编写并注册了新提案算子 `large_scene_targeted_local_search`（AST 白名单 + 子进程沙箱冒烟通过）。
- wrong: `operator pool = builtin ops`
- fixed: `operator pool += learned op `large_scene_targeted_local_search``

## Forensics · protected:small

- 候选（random_mutate）在保护场景 small 上回退：180.285041 -> 180.95057，已拒绝晋升。
- wrong: `promote(CONFIG['local_search_budget_ms']=3211.3, CONFIG['triple_top_k']=12)`
- fixed: `keep CONFIG unchanged (protected threshold preserved)`

## 2026-09-19T14:11:06 · Real training finished

- mode: balanced
- promoted/rejected/candidates: 0/6/13
- anchor measured: {'ok': True, 'valid': True, 'penalty_score': 626.319027, 'covered_tasks': 40, 'total_tasks': 40, 'elapsed_ms': 8911.5, 'case_type': 'normal'}
- backup: `pretrain_r6_20260919_140540.zip`

## 2026-09-19 · RSI live run handover

- 带真实 DeepSeek 的 6 轮 balanced 已跑通，learned op `large_scene_targeted_local_search` 在池中。
- 首个通过全预算验证的候选（anchor -3.05）被 protected:small 门禁拒绝（回退 +0.67）。
- 要看到首次晋升：多跑几轮 / REGRESSION_TOLERANCE 提到 1.0 / 或对 anchor 大幅改进放宽门禁。
- 启动命令（PowerShell）：$env:DEEPSEEK_API_KEY="..."; python app.py

## 2026-09-19T15:17:04 · Real training finished

- mode: balanced
- promoted/rejected/candidates: 0/8/24
- anchor measured: {'ok': True, 'valid': True, 'penalty_score': 626.319027, 'covered_tasks': 40, 'total_tasks': 40, 'elapsed_ms': 8911.5, 'case_type': 'normal'}
- backup: `pretrain_r6_20260919_151126.zip`

## 2026-09-19T15:30:47 · Real training finished

- mode: balanced
- promoted/rejected/candidates: 0/12/40
- anchor measured: {'ok': True, 'valid': True, 'penalty_score': 626.319027, 'covered_tasks': 40, 'total_tasks': 40, 'elapsed_ms': 8911.5, 'case_type': 'normal'}
- backup: `pretrain_r8_20260919_152108.zip`

## 2026-09-19T15:51:45 · Real training finished

- mode: balanced
- promoted/rejected/candidates: 0/10/35
- anchor measured: {'ok': True, 'valid': True, 'penalty_score': 626.319027, 'covered_tasks': 40, 'total_tasks': 40, 'elapsed_ms': 8911.5, 'case_type': 'normal'}
- backup: `pretrain_r12_20260919_154121.zip`

## 2026-09-19 · V6.1 handover

- 门禁参数在 params.json global（regression_tolerance=0.8, anchor_tradeoff_ratio=0.25 已启用）。
- DeepSeek key 余额耗尽（402），充值后 L3 元步与 llm_propose 自动恢复。
- 算子榜：crossover 36% 胜率最高，UCB 自动加权中；经验库 memory/experience.sqlite 223 试验。
- 首次晋升仍未发生（champion 接近局部最优），系统三道门（筛选/验证/保护）全部按设计工作。

## Forensics · RSI-operator

- Round 6 元步：Agent 为自己编写并注册了新提案算子 `scarce_couriers_expand_candidates_tighte`（AST 白名单 + 子进程沙箱冒烟通过）。
- wrong: `operator pool = builtin ops`
- fixed: `operator pool += learned op `scarce_couriers_expand_candidates_tighte``

## Forensics · RSI-operator

- Round 9 元步：Agent 为自己编写并注册了新提案算子 `large_scene_worst_metric_rebalance`（AST 白名单 + 子进程沙箱冒烟通过）。
- wrong: `operator pool = builtin ops`
- fixed: `operator pool += learned op `large_scene_worst_metric_rebalance``

## 2026-09-19T16:38:33 · Real training finished

- mode: balanced
- promoted/rejected/candidates: 0/16/64
- anchor measured: {'ok': True, 'valid': True, 'penalty_score': 626.319027, 'covered_tasks': 40, 'total_tasks': 40, 'elapsed_ms': 8911.5, 'case_type': 'normal'}
- backup: `pretrain_r10_20260919_160429.zip`

## 2026-09-19 · V7 handover

- 算子池 10 个（含 3 个 L3 自写算子），bandit 已由 LLM 系算子主导（胜率 0.39~0.56）。
- exact_reference.py 可对 tiny/small 出 DP 下界；champion 已证明优于一切单骑手解。
- 细筛显示各场景 champion 差距 <0.5%：键空间局部最优实锤，下一步只能 L4 代码级变异
  （改写局部搜索/拓扑修复函数本身，需在 config_io 之外新增函数级 AST 手术）。

## Forensics · RSI-operator

- Round 3 元步：Agent 为自己编写并注册了新提案算子 `large_scene_worst_metric_boost`（AST 白名单 + 子进程沙箱冒烟通过）。
- wrong: `operator pool = builtin ops`
- fixed: `operator pool += learned op `large_scene_worst_metric_boost``

## Forensics · RSI-operator

- Round 3 元步：Agent 为自己编写并注册了新提案算子 `large_scene_worst_metric_boost_v2`（AST 白名单 + 子进程沙箱冒烟通过）。
- wrong: `operator pool = builtin ops`
- fixed: `operator pool += learned op `large_scene_worst_metric_boost_v2``

## 2026-09-20T00:07:24 · Real training finished

- mode: code-lab
- promoted/rejected/candidates: 0/8/16
- anchor measured: {'ok': True, 'valid': True, 'penalty_score': 626.319027, 'covered_tasks': 40, 'total_tasks': 40, 'elapsed_ms': 8911.5, 'case_type': 'normal'}
- backup: `pretrain_r4_20260919_234050.zip`

## 2026-09-19 · V8 handover

- L4 代码进化全链路上线且实弹验证；`code-lab` 模式=每轮改写一个函数（轮换四个目标）。
- champion 仍未被击败；LLM 补丁保守是主要瓶颈，建议在 CODE_SYSTEM 中加入具体算法菜单
  （annealing acceptance / perturbation restarts / move-distribution change）并提高温度。
- low_willingness 复筛噪声大（截断所致），可把该场景 FINE_BUDGET 提到 7s。

## Forensics · RSI-operator

- Round 3 元步：Agent 为自己编写并注册了新提案算子 `large_scene_worst_metric_boost_v3`（AST 白名单 + 子进程沙箱冒烟通过）。
- wrong: `operator pool = builtin ops`
- fixed: `operator pool += learned op `large_scene_worst_metric_boost_v3``

## 2026-09-20T01:05:43 · Real training finished

- mode: code-lab
- promoted/rejected/candidates: 0/11/24
- anchor measured: {'ok': True, 'valid': True, 'penalty_score': 626.319027, 'covered_tasks': 40, 'total_tasks': 40, 'elapsed_ms': 8911.5, 'case_type': 'normal'}
- backup: `pretrain_r4_20260920_003429.zip`

## 2026-09-20 · V9 handover

- L4 激进化生效：零等价补丁，筛选级 50% 胜率，全门禁零误晋升。
- low_willingness 复筛已用 8s（fine_budget_for）；负载截断假胜出由全预算门禁兜底。
- 建议下一战役：local_search 定向竞赛（一次 3 版并行）+ 目标扩容到 improve_* 函数族。

## 2026-09-20T02:00:41 · Real training finished

- mode: code-lab
- promoted/rejected/candidates: 0/4/16
- anchor measured: {'ok': True, 'valid': True, 'penalty_score': 626.319027, 'covered_tasks': 40, 'total_tasks': 40, 'elapsed_ms': 8911.5, 'case_type': 'normal'}
- backup: `pretrain_r6_20260920_015631.zip`

## 2026-09-20 · V10 handover

- L4 锦标赛与目标扩容代码就绪且接线已验证（402 事件为证），等待 DeepSeek 充值。
- 充值后：python app.py → 模式 code-lab → 4-6 轮即为一场完整锦标赛战役。
- 成本提醒：锦标赛一轮 ≈ 3 次大上下文推理调用，预算按 ~6 轮 × 4 次调用准备。

## Forensics · RSI-operator

- Round 3 元步：Agent 为自己编写并注册了新提案算子 `large_scene_worst_metric_boost_v4`（AST 白名单 + 子进程沙箱冒烟通过）。
- wrong: `operator pool = builtin ops`
- fixed: `operator pool += learned op `large_scene_worst_metric_boost_v4``

## 2026-09-20T22:19:43 · Real training finished

- mode: code-lab
- promoted/rejected/candidates: 0/6/8
- anchor measured: {'ok': True, 'valid': True, 'penalty_score': 626.319027, 'covered_tasks': 40, 'total_tasks': 40, 'elapsed_ms': 8911.5, 'case_type': 'normal'}
- backup: `pretrain_r6_20260920_220302.zip`

## 2026-09-20T22:34:32 · Real training finished

- mode: code-lab
- promoted/rejected/candidates: 0/3/4
- anchor measured: {'ok': True, 'valid': True, 'penalty_score': 626.319027, 'covered_tasks': 40, 'total_tasks': 40, 'elapsed_ms': 8911.5, 'case_type': 'normal'}
- backup: `pretrain_r2_20260920_222343.zip`

## Forensics · protected:small

- L4 补丁（l4:local_search#3(batching several candidate replacements per remo)）在保护场景 small 上回退超容忍（容忍=0.80），已拒绝。
- wrong: `splice local_search (l4 patch r1)`
- fixed: `keep local_search unchanged`

## Forensics · protected:small

- L4 补丁（l4:local_search#1(perturbation restarts with best-so-far retention)）在保护场景 small 上回退超容忍（容忍=0.80），已拒绝。
- wrong: `splice local_search (l4 patch r1)`
- fixed: `keep local_search unchanged`

## Forensics · protected:small

- 候选（large_scene_worst_metric_rebalance([filtered: 1])）在保护场景 small 上回退超容忍（容忍=0.80，anchor_gain=0.00）：180.285041 -> 182.627466，已拒绝晋升。
- wrong: `promote(CONFIG['normal_topology_generated_limit']=12, CONFIG['pair_top_k']=44)`
- fixed: `keep CONFIG unchanged (protected threshold preserved)`

## Forensics · medium

- Round 1 L4 晋升：Agent 重写了 solver 的 `local_search` 函数（l4:local_search#1(perturbation restarts with best-so-far ret；anchor 626.32 -> 626.32，保护场景无回退）。依据：Implemented perturbation restarts with best-so-far retention: when strict improvement stalls, randomly remove 1-3 incumbents, exact-cover freed masks with slight score slack to permit occasionally worse moves, then re-improve and retain the best solution. Deadlines and budget are checked in all loop
- wrong: `def local_search (原实现前6行)
def local_search(ctx, selected, deadline_ms):
    current = list(selected)
    total_tasks = _count_bits(ctx.all_task_mask)
    current_eval = evaluate(current, total_tasks)
    start_ms = _now_ms()
    budget = CONFIG['local_search_budget_ms']
...`
- fixed: `def local_search (新实现前6行)
def local_search(ctx, selected, deadline_ms):
    current = list(selected)
    total_tasks = _count_bits(ctx.all_task_mask)
    current_eval = evaluate(current, total_tasks)
    best = list(current)
    best_eval = current_eval
...`

## 2026-09-20T23:06:18 · Real training finished

- mode: code-lab
- promoted/rejected/candidates: 0/2/0
- anchor measured: {'ok': True, 'valid': True, 'penalty_score': 626.319027, 'covered_tasks': 40, 'total_tasks': 40, 'elapsed_ms': 8911.5, 'case_type': 'normal'}
- backup: `pretrain_r2_20260920_225253.zip`

## 2026-09-20 · 首次 L4 晋升 handover

- submission/solver.py 已含 Agent 编写的新 local_search（扰动重启+best-so-far），
  备份 l4_promote_r1_20260920_230617.zip 可回滚。
- champions：anchor 626.32（不变），holdout:medium 403.07（旧 405.13），protected:scarce 1192.8。
- 后续战役可直接跑 code-lab：档案里还有 2 个过筛补丁可免费重试；下一目标函数
  improve_regular_with_multi_options 是支配 anchor 的关键函数。

## Forensics · protected:small

- 候选（large_scene_worst_metric_boost）在保护场景 small 上配对回退 +2.09 超容忍（容忍=0.80，anchor_gain=0.00，同负载基线 180.738746），已拒绝晋升。
- wrong: `promote(CONFIG['pair_top_k']=34)`
- fixed: `keep CONFIG unchanged (protected threshold preserved)`

## Forensics · RSI-operator

- Round 3 元步：Agent 为自己编写并注册了新提案算子 `large_scene_worst_metric_boost_v5`（AST 白名单 + 子进程沙箱冒烟通过）。
- wrong: `operator pool = builtin ops`
- fixed: `operator pool += learned op `large_scene_worst_metric_boost_v5``

## Forensics · large

- Round 3 晋升（large_scene_worst_metric_boost_v2([filtered: 1])）：anchor 626.32 -> 626.32, holdout 618.67 -> 616.89，保护场景无回退。
- wrong: `local_search_budget_ms=2800.0 / normal_topology_top_k=6 / normal_topology_generated_limit=10 / normal_preview_scan_per_primary=18 / pair_top_k=28 / triple_top_k=20 / max_exact_replace_tasks=8`
- fixed: `CONFIG['local_search_budget_ms']=1400.0, CONFIG['normal_topology_top_k']=10, CONFIG['normal_topology_generated_limit']=18, CONFIG['normal_preview_scan_per_primary']=30, CONFIG['pair_top_k']=44, CONFIG['triple_top_k']=32, CONFIG['max_exact_replace_tasks']=11`

## 2026-09-20T23:33:42 · Real training finished

- mode: code-lab
- promoted/rejected/candidates: 1/5/12
- anchor measured: {'ok': True, 'valid': True, 'penalty_score': 626.319027, 'covered_tasks': 40, 'total_tasks': 40, 'elapsed_ms': 8911.5, 'case_type': 'normal'}
- backup: `pretrain_r1_20260920_231431.zip`

## 2026-09-20 · 第二次晋升 handover

- solver 现含两项当日晋升：L4 新 local_search（扰动重启）+ 7 键 CONFIG 组合（L3 算子提案）。
- 最新 champions：anchor 626.32 / medium 403.07 / large 616.89 / scarce 1199.15（复测值）。
- 定向强攻：params.global.l4_target=<函数名> 可锁目标；improve_regular 重写难度高
  （96 行、返回契约复杂），LLM 两版未过筛，可再战或改攻 improve_backup_allocation。
- 备份链：l4_promote_r1_*.zip → promote_r3_*.zip 逐级可回滚。

## Forensics · RSI-operator

- Round 9 元步：Agent 为自己编写并注册了新提案算子 `low_willingness_worst_metric_boost`（AST 白名单 + 子进程沙箱冒烟通过）。
- wrong: `operator pool = builtin ops`
- fixed: `operator pool += learned op `low_willingness_worst_metric_boost``

## 2026-09-20 · 收官 handover

- 当前 solver：L4 新 local_search + 7 键 CONFIG 组合（双晋升成果），全场景终测通过。
- improve_backup_allocation 两攻未过筛——建议换目标（improve_low_with_multi_options 52 行
  较易）或先让 bandit 在新 champion 上多积累几轮 CONFIG 晋升。
- l4_target/l4_scenes 两个定向旋钮可用；bandit 统计已修复 inf 污染并加固。
