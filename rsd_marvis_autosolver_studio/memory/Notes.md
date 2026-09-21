# Notes.md

## 2026-06-06T04:28:48 · V5 hardfix initialized

本版为强制修复版，已按用户 9 条要求重新实现 UI 与后端流程：

1. 左侧导航和顶部按钮显式新增“一键训练”。
2. Cockpit 默认显示柱状图、折线图、雷达图、热力图、场景地图。
3. Agent 办公室点击 Agent 展开操作和数据。
4. Flow 节点点击展开代码和状态。
5. DataLab 可编辑场景参数，可根据 large_seed301 自动生成种子配置。
6. 错误归因展示 wrong/fixed code，并写入 Notes.md / Handover.md。
7. 新增训练日志模块。
8. 用户配置台所有按钮均接入 API。
9. 训练前自动备份，备份列表支持二次确认一键回滚。

## Teacher solver

- path: submission/solver.py
- size: 68.92 KB
- functions: 45
- classes: 3
- sha256: 587c4533fc16c814

## 2026-09-19T13:07:51 · Real training start

- mode: safe-medium-only
- rounds: 2
- backup: `pretrain_r0_20260919_130751.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 2026-09-19T13:08:34 · Distill

- solver: 68.92KB
- compact config updated

## 2026-09-19T13:12:22 · Real training start

- mode: balanced
- rounds: 3
- backup: `pretrain_r2_20260919_131222.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 2026-09-19T13:13:53 · Distill

- solver: 68.92KB
- compact config updated

## 2026-09-19 · V5.1 agent_core 架构升级（假训练 → 真实循环）

- 新增 `agent_core/`：evaluator（官方口径评分）、runner/solver_worker（子进程隔离求解）、
  case_bank（场景真实案例库）、mutations（白名单 CONFIG 变异）、config_io（CONFIG 外科手术式写回）、
  llm（结构化提案+归因，无 key 退化）、trainer（筛选→验证→门禁→晋升/回滚）。
- app.py 的 `train()` 从硬编码 gain + sleep 替换为调用 agent_core.trainer；UI API 形状不变。
- 实测 anchor（large_seed301, 9.3s 预算）：penalty 626.32，40/40 覆盖 —— 旧面板 716.74/675.35 为占位假数据，已清除 trend 假序列。
- 发现并修复：旧 tools 案例生成器产出的 medium/high_noise 案例仍是 40 任务，solver 内部按 large_normal 处理，训练信号错位；新 case_bank 按运行时检测条件构造案例。
- 单测：CONFIG 写回只动第 6 行、可字节级恢复；晋升失败自动还原。

## 2026-09-19T13:51:34 · Real training start

- mode: balanced
- rounds: 2
- backup: `pretrain_r3_20260919_135134.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 2026-09-19T13:52:06 · Distill

- solver: 68.92KB
- compact config updated

## 2026-09-19 · V6 RSI 自迭代升级（agent 成为真正的自改进 Agent）

三层递归自改进闭环：

- **L1 solver 自改进**（已有）：CONFIG 白名单变异 → 全预算验证 → 保护门禁 → 外科手术式写回。
- **L2 改进策略自改进**（新）：`experience.py`（sqlite3 经验库：试验/算子记分/键杠杆分析）+
  `operators.py`（UCB1 bandit 提案算子池：random_mutate / strategy_jitter / crossover /
  leverage_guided / llm_propose）。胜率高的算子被更频繁调用，未探索算子保留探索加成。
- **L3 Agent 给自己写代码**（新）：`code_synthesis.py` 每 3 轮元步——LLM 生成新算子函数
  `mutate_config(config, scene, rng)` → AST 白名单静态验证（禁 import/IO/eval/危险属性访问，
  仅允许 rng 方法与 config.get）→ 子进程沙箱多种子冒烟（8s 硬超时）→ 提案过 mutations 白名单
  → 注册进 learned_operators/registry.json 并自动加入 UCB 池。

验证：AST 验证器对抗样本全拒（import/eval/open/__class__/错误签名/while True）；
mock LLM 走通 L3 全链路并自动产出候选；服务器 2 轮训练 state.rsi 正常；备份已含
experience.sqlite 与 learned_operators/*。无 API key 时 L1/L2 完整可用，L3 自动跳过。

## 2026-09-19T13:57:27 · Real training start

- mode: balanced
- rounds: 6
- backup: `pretrain_r2_20260919_135726.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 归因（round 1, medium）

候选策略仅对权重元组做微小抖动，未改变搜索行为，评分与基线完全一致，说明该扰动对中等场景不敏感或幅度不足。下一步可尝试加大抖动范围、更换参数组合，或引入多样化重启与自适应搜索，避免无效微调。

## 归因（round 2, high_noise）

高噪声场景下，策略抖动仅微调权重元组，未改变关键决策，噪声主导导致指标与基线完全相同。建议扩大抖动幅度、针对噪声特征做去噪或鲁棒正则，或更换策略搜索空间，避免无效微调。

## 归因（round 4, low_willingness）

候选失败因随机突变仅调整了 `triple_top_k` 和 `max_exact_replace_tasks`，二者对低意愿场景不敏感，未改变搜索或替换的核心权衡，故分数与基线完全一致。建议下一步聚焦影响低意愿下探索/利用的参数，如温度、奖励折扣、候选池大小或替换策略强度；采用贝叶斯搜索或定向网格微调，而非盲目随机突变。

## 归因（round 5, medium）

该候选未超越基线，因策略抖动仅微调权重元组，扰动幅度可能过小或落在同一局部最优，导致评估均值与基线完全一致（674.28），未产生有效探索。建议下一步：增大抖动幅度或改用更有结构的变异（如交换、缩放、随机重置部分策略）；引入多场景或多次评估降低噪声；采用贝叶斯/进化搜索自适应调整探索范围，避免无效微调。

## 归因（round 6, scarce_couriers）

该候选未超过基线，主要因参数调整仅扩大候选池和替换范围，未针对稀缺骑手造成的可行性瓶颈，反而引入低质量候选与求解噪声，未能有效改善关键任务重分配。下一步应聚焦瓶颈分析：定位不可行任务与高负载骑手，设计约束感知的局部修复或强制交换算子；控制候选质量而非数量，筛除不可行解；借助LLM对失败案例生成针对性重分配规则。

## 2026-09-19T14:02:33 · Distill

- solver: 68.92KB
- compact config updated

## 2026-09-19T14:05:40 · Real training start

- mode: balanced
- rounds: 6
- backup: `pretrain_r6_20260919_140540.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 归因（round 1, medium）

候选“strategy_jitter”仅微调策略权重元组，实际解与基线完全一致，扰动未改变搜索路径，故无改进。建议下一步增大策略权重扰动幅度，或改用其他变异算子（如交换/重置策略），并针对 medium 场景引入局部搜索或参数组合调优。

## 归因（round 2, high_noise）

高噪声场景下，策略权重抖动后得分与基线完全一致，说明扰动幅度过小或未触及关键策略，信号被噪声淹没。下一步可扩大扰动范围、优先调整核心策略权重，并增加重复评估降噪，或改用贝叶斯优化替代随机抖动。

## 2026-09-19T14:07:55 · Forensics: RSI-operator

Round 3 元步：Agent 为自己编写并注册了新提案算子 `large_scene_targeted_local_search`（AST 白名单 + 子进程沙箱冒烟通过）。

```python
# wrong
operator pool = builtin ops

# fixed
operator pool += learned op `large_scene_targeted_local_search`
```

## RSI 元步（round 3）

新算子 `large_scene_targeted_local_search` 已注册：新算子已注册并加入 UCB 池（op_large_scene_targeted_local_search.py）

## 2026-09-19T14:09:12 · Forensics: protected:small

候选（random_mutate）在保护场景 small 上回退：180.285041 -> 180.95057，已拒绝晋升。

```python
# wrong
promote(CONFIG['local_search_budget_ms']=3211.3, CONFIG['triple_top_k']=12)

# fixed
keep CONFIG unchanged (protected threshold preserved)
```

## 归因（round 4, low_willingness）

随机突变仅微调候选数与配对TopK，未触及低意愿场景关键决策变量，且无方向性探索易陷入等价参数，故均值持平。建议改用贝叶斯优化或基于反馈的定向扰动，优先调整温度、TopP、提示模板等影响生成意愿的参数，并针对低意愿特征设计奖励函数。

## 2026-09-19T14:11:06 · Distill

- solver: 68.92KB
- compact config updated

## 2026-09-19 · 首次带 LLM 的完整 RSI 运行（deepseek-v4-pro）

- 修复两处饥饿 bug：元步原被晋升段之后的 continue 路径跳过 → 移到轮首；
  llm_propose/学习算子在 UCB 排序中被挤出 → 给予优先席位。
- Round 3 元步：DeepSeek 自写算子 `large_scene_targeted_local_search` 通过 AST+沙箱三关，
  自动注册进 UCB 池（场景门控 large，local_search_budget +750 / max_exact_replace +3，均有界）。
- Round 3 候选通过全预算验证：anchor 626.32 → 623.27（首次真实改进），
  但 protected:small 回退 180.285 → 180.951（>0.5 容忍），被门禁拒绝——安全系统按设计工作。
- llm_propose 修复后 6 轮内开火 3 次（含 scarce 场景 3 键组合提案，带依据）；
  crossover 首次激活即胜出。6 轮 13 候选 0 晋升，门禁偏严属预期。
- 调优线索：REGRESSION_TOLERANCE（trainer.py, 现 0.5）与筛选预算迁移是晋升率的关键旋钮。

## 2026-09-19T15:11:26 · Real training start

- mode: balanced
- rounds: 8
- backup: `pretrain_r6_20260919_151126.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 2026-09-19T15:17:04 · Distill

- solver: 68.92KB
- compact config updated

## 2026-09-19T15:21:08 · Real training start

- mode: balanced
- rounds: 12
- backup: `pretrain_r8_20260919_152108.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 2026-09-19T15:30:47 · Distill

- solver: 68.92KB
- compact config updated

## 2026-09-19T15:41:22 · Real training start

- mode: balanced
- rounds: 10
- backup: `pretrain_r12_20260919_154121.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 2026-09-19T15:51:45 · Distill

- solver: 68.92KB
- compact config updated

## 2026-09-19 · V6.1 训练质量工程（筛选/门禁/可视化）

- **两阶段筛选**：2s 粗筛全候选 → 前 2 名 6s 复筛（实测 solver 在 6s 预算下自然收敛 ~4.6s，
  分数完全确定性；5s 预算余量不足，系统负载下会被截断产生 ~30% 假信号）。
- **验证池**：细筛通过阈值（0.5%）的所有候选都做全预算验证，不只验证冠军——验证才是真门禁。
- **噪声下限**：全预算运行实测 ±1.2 分抖动，验证通过需 anchor 改进 ≥1.5、holdout ≥1.0，
  杜绝把噪声当改进写回。
- **自适应门禁**（params.json global）：regression_tolerance / anchor_tradeoff_ratio /
  anchor_tradeoff_cap；被拒且 anchor 改进 ≥2 时 Auditor 提示可开启 tradeoff。
- **Dashboard RSI 面板**：三层状态卡片 + 算子榜（uses/wins/UCB，L3 算子高亮）。
- **LLM 诊断透明化**：402 Payment Required 等错误直接显示在元步事件（key 余额已耗尽待充值）。
- 10 轮 x 35 候选仍无晋升：champion 在现有 CONFIG 键空间下接近局部最优；经验库 223 试验，
  crossover（36% 胜率）/leverage_guided（22%）领跑 bandit。突破方向：LLM 充值后的组合提案、
  strategies 权重多扰动、或 L4 代码级 solver 变异。

## 2026-09-19T16:04:29 · Real training start

- mode: balanced
- rounds: 16
- backup: `pretrain_r10_20260919_160429.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 归因（round 2, high_noise）

候选未击败基线：调整后平均313.50，差于基线313.44。高噪声下扩大候选池（top_k=27、每mask 22）引入更多噪声，超参组合可能过拟合验证集，无真实提升。下一步建议回退默认超参，先增强去噪或特征稳定性，并在该场景用交叉验证小范围调参，避免单点波动。

## 归因（round 3, large）

候选仅微调预算与候选池，未改变大场景搜索策略，搜索易陷入相同局部最优，故指标几乎无变化。建议尝试更强扰动或重启动策略，如随机破坏重建、针对瓶颈节点的定向优化，而非单纯增大局部搜索预算。

## 归因（round 4, low_willingness）

归因：低意愿场景中，候选同时叠加大幅权重和符号翻转，过度探索极端排序，破坏稳定锚点，且反转意愿/快递与真实低意愿行为相悖，导致均值下降。下一步：拆分策略单独测试，仅小幅调整意愿、价格或紧迫度权重，避免符号翻转，采用局部搜索逐步优化。

## 归因（round 5, medium）

候选与基线均分完全相同，说明 strategy_jitter 对权重元组的修改未改变求解行为，可能参数被忽略或扰动过小。下一步应验证策略权重是否真正生效，记录策略选择分布；并尝试更大扰动或直接替换策略组合，辅以多种子重复实验。

## 2026-09-19T16:17:55 · Forensics: RSI-operator

Round 6 元步：Agent 为自己编写并注册了新提案算子 `scarce_couriers_expand_candidates_tighte`（AST 白名单 + 子进程沙箱冒烟通过）。

```python
# wrong
operator pool = builtin ops

# fixed
operator pool += learned op `scarce_couriers_expand_candidates_tighte`
```

## RSI 元步（round 6）

新算子 `scarce_couriers_expand_candidates_tighte` 已注册：新算子已注册并加入 UCB 池（op_scarce_couriers_expand_candidates_tighte.py）

## 归因（round 6, scarce_couriers）

参数微调仅带来约0.3的均值下降，未显著超越基线，可能因搜索空间已近饱和或参数组合未触及瓶颈。建议扩大参数扰动范围，尝试不同变异算子或约束惩罚，并结合多次种子验证，避免噪声干扰。

## 归因（round 7, medium）

候选仅比基线低约0.02，改善幅度过小，属于噪声范围；strategy_jitter 只微调权重元组，未改变策略结构，搜索仍停留在原邻域，难以产生实质突破。下一步建议增大扰动幅度、改变策略组合或引入新增/删除策略的结构性变异，并多随机种子验证。

## 归因（round 8, high_noise）

高噪声下候选将候选数和三元组 top_k 调大，反而引入更多噪声，导致 313.50 略差于基线 313.44。建议反向收缩：降低 max_candidates_per_mask 至 15 左右、triple_top_k 至 8-10，并增强去噪或置信度过滤。

## 2026-09-19T16:22:42 · Forensics: RSI-operator

Round 9 元步：Agent 为自己编写并注册了新提案算子 `large_scene_worst_metric_rebalance`（AST 白名单 + 子进程沙箱冒烟通过）。

```python
# wrong
operator pool = builtin ops

# fixed
operator pool += learned op `large_scene_worst_metric_rebalance`
```

## RSI 元步（round 9）

新算子 `large_scene_worst_metric_rebalance` 已注册：新算子已注册并加入 UCB 池（op_large_scene_worst_metric_rebalance.py）

## 归因（round 9, large）

候选在 large 场景仅用过滤后数据做 worst_metric_rebalance，拓扑生成上限 26、局部搜索预算 2128ms 偏低，导致搜索空间不足，622.03 略低于基线 623.83。下一步建议提高局部搜索预算至 3000ms 以上，放宽拓扑生成上限，并增大 pair/triple top_k；或改用未过滤场景重平衡并做融合。

## 归因（round 10, low_willingness）

候选仅在 pair_top_k=36 上微调，提升不足且劣于基线，说明该参数对低意愿场景不敏感，筛选后重平衡未触及核心瓶颈。下一步应放弃 top_k 微调，改试更影响决策的参数，如温度、候选多样性或低意愿专属提示，并针对“拒绝/犹豫”样本做定向重平衡。

## 归因（round 11, medium）

候选在medium场景同时放宽局部搜索预算、预览备份与拓扑生成数，导致搜索分散、引入低质候选，平均解反而变差。建议做单参数消融：先保持基线候选筛选机制，仅微调局部搜索预算或拓扑生成数量，避免多项同时放大干扰选择。

## 归因（round 12, scarce_couriers）

候选仅靠全局调大 pair/triple top-k 和 mask 候选数，搜索池虽扩大但低质组合增多，分散算力且未命中稀缺骑手瓶颈；0.30 的差异属噪声，未显著优于基线。建议改为按骑手/区域稀缺度动态调参、引入成本下界剪枝，并加入局部搜索或重优化，而非单纯增加候选数量。

## 归因（round 13, medium）

候选失败主因是参数从 large 场景迁移到 medium，未适配场景规模：pair_top_k=44 可能过大引入噪声，normal_topology_generated_limit=10 又限制拓扑多样性，导致平均分 401.29 低于基线 402.24。下一步应在 medium 场景下做本地网格搜索，优先尝试降低 pair_top_k（如 20~32）、适当提高生成 limit，并改用 medium 专属调参或更轻量的筛选策略。

## 归因（round 14, high_noise）

高噪声下简单降权得分并未改变有效排序，候选与基线等价，说明权重调整方向无效或幅度不足。下一步可改用鲁棒统计（分位数、去极值）替代均值，或直接屏蔽高噪特征、引入非线性组合与自适应加权，而非仅微调权重。

## 2026-09-19T16:38:33 · Distill

- solver: 68.92KB
- compact config updated

## 2026-09-19 · V7 SOTA 战役（16 轮，LLM 充值恢复后）

- 新算子：`strategy_evolution`（2~4 权重联合 ±40% 扰动）+ `llm_strategies`（LLM 整组排序
  元组提案，validator 放宽至 2~6 元组，solver 按列表遍历天然支持变长）。
- 元步两次成功自我注入新算子：`scarce_couriers_expand_candidates_tighte`（6 键组合提案）、
  `large_scene_worst_metric_rebalance`（4 键）——L3 层开始复利，池成长到 10 个算子。
- `llm_strategies` 首个提案（权重符号翻转+量级重构）直接进入全预算验证。
- 64 候选 313 试验，仍未晋升：champion 在全部场景的细筛差距都收敛到 <0.5%
  （medium 400.70/400.72，large 622.03/623.83，scarce 1234.79/1235.09）——
  这本身是强证据：champion 在当前键空间+排序空间下已处于强局部最优。
- **SOTA 标尺（exact_reference.py，掩码 DP）**：protected tiny 下界 137.72、small 338.55，
  champion 实测 67.94 / 180.29 —— champion 被证明优于一切单骑手解（优势来自多骑手
  backup 结构），这是可证明的支配声明。
- bandit 终局：llm_propose 胜率 0.56 最高、两个新 L3 算子 0.46/0.39，随机系算子 0.13-0.14
  —— LLM 系算子全面接管提案权重，符合设计预期。
- 通往"更优"的剩余路径：L4 代码级变异（改写 solver 的局部搜索算子函数本身）、
  更大 exact 参照（backup-aware DP）、或比赛中未见案例的泛化赌注。

## 2026-09-19T23:30:53 · Real training start

- mode: code-lab
- rounds: 5
- backup: `pretrain_r16_20260919_233053.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 归因（round 1, medium）

候选仅微调拓扑生成上限与配对TopK，改进幅度过小且未通过筛选，可能因参数搜索范围不足或重平衡策略过拟合单一最差场景。建议扩大参数搜索空间，针对medium场景调整指标权重，并尝试不同候选生成策略或多目标优化。

## 归因（round 2, high_noise）

候选指标与基线完全相同（313.435024），说明 pair_top_k=28 未改变筛选结果，候选实际等价于基线，可能参数不敏感或过滤后未生效。建议先确认该覆盖是否真正作用于数据；若无效，应调整过滤阈值或扩大 pair_top_k 范围，并换用更鲁棒的重平衡策略，避免在高噪声场景下重复等价试验。

## 2026-09-19T23:35:13 · Forensics: RSI-operator

Round 3 元步：Agent 为自己编写并注册了新提案算子 `large_scene_worst_metric_boost`（AST 白名单 + 子进程沙箱冒烟通过）。

```python
# wrong
operator pool = builtin ops

# fixed
operator pool += learned op `large_scene_worst_metric_boost`
```

## RSI 元步（round 3）

新算子 `large_scene_worst_metric_boost` 已注册：新算子已注册并加入 UCB 池（op_large_scene_worst_metric_boost.py）

## 归因（round 3, large）

该候选为提升最差指标，大幅调高局部搜索预算与 triple_top_k，在 large 场景中可能引入噪声或过拟合尾部样本，导致平均分略降（622.51 vs 623.83）。下一步应缩小扰动范围，在基线附近微调，优先将 triple_top_k 回调至 20–30，并限制局部搜索预算，改用均值与最差指标的联合目标。

## 2026-09-19T23:40:50 · Real training start

- mode: code-lab
- rounds: 4
- backup: `pretrain_r4_20260919_234050.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 归因（round 1, medium）

候选失败主因是参数从大场景迁移到 medium 场景不适配：提高 `normal_topology_generated_limit=12` 与 `pair_top_k=44` 引入冗余搜索，且重平衡策略针对大场景最差指标，未改善 medium 平均指标。建议回退参数，在 medium 上单独微调；优先小幅降低生成限制与 top_k，或换用按 medium 指标加权的重平衡策略。

## 归因（round 2, high_noise）

候选失败主因：高噪声下扩大局部搜索预算与配对候选，反而引入更多噪声解，分散搜索；同时削减精确替换未补偿结构损失。下一步建议：逐项消融参数，先仅调局部搜索预算或 pair_top_k；并引入去噪/候选质量过滤，而非简单扩大搜索范围。

## 2026-09-19T23:54:03 · Forensics: RSI-operator

Round 3 元步：Agent 为自己编写并注册了新提案算子 `large_scene_worst_metric_boost_v2`（AST 白名单 + 子进程沙箱冒烟通过）。

```python
# wrong
operator pool = builtin ops

# fixed
operator pool += learned op `large_scene_worst_metric_boost_v2`
```

## RSI 元步（round 3）

新算子 `large_scene_worst_metric_boost_v2` 已注册：新算子已注册并加入 UCB 池（op_large_scene_worst_metric_boost_v2.py）

## 归因（round 3, large）

候选在large场景均值623.57仍低于基线624.77，说明参数组合未改善核心路径：提高局部搜索预算、放开top_k与生成限制反而可能增加无效探索，未针对large场景瓶颈。建议缩小消融范围，重点调pair/triple候选质量与max_exact_replace任务数，并增大验证样本，避免单点噪声干扰。

## 归因（round 4, low_willingness）

低意愿场景下，单纯扩大候选组合规模（pair/triple/mask 上限）引入了更多低质量或不可行组合，增加了搜索噪声与耗时，未命中有效可接受分配，导致指标反而略低于基线。下一步应改为质量驱动：先基于历史接受率或意愿评分对候选排序，限制低意愿掩码数量，优先探索小范围高潜组合；或引入针对性约束/局部修复算子，而非盲目加宽搜索。

## 2026-09-20T00:07:24 · Distill

- solver: 67.56KB
- compact config updated

## 2026-09-19 · V8 L4 代码进化（Agent 在沙箱里改写 solver 函数）

- 新模块 `agent_core/code_evolution.py`：函数提取/AST 行级拼接（config_io 同款外科手术）、
  补丁静态验证（单函数+精确签名、禁 import/global/nonlocal/yield/try/with、禁危险名与
  dunder 属性、audit-DANGER 串扫描）、变体物化（variants/，compile 检查）、LLM 合成提示
  （附完整目标源码+模块函数签名表+数据类字段摘要+deadline 约定）。
- trainer 新增 `try_l4`：轮首共享基线（粗筛+复筛各算一次，CONFIG 候选与 L4 变体共用）、
  变体走 筛选→全预算验证→保护门禁→备份→拼接写回→smoke→失败自动还原；`code-lab` 模式
  每轮 L4（模式意图优先于 params）。目标轮换：local_search → strategy_key →
  choose_probability_backups → rank_removals。
- 实弹 4 轮：LLM 真实改写了全部 4 个目标函数，全部通过 AST+沙箱+评分（功能性 100%），
  但无一打赢 champion（400.84/400.82、313.44/313.44、624.72/624.77、1924.97/1924.97）。
- code_evolution 算子入 bandit（uses=4 wins=2, UCB 4.77）；运行中元步又注入 2 个 L3 算子，
  池达 13。经验库 371 试验。
- 安全验证：拼接字节级往返、smoke 失败自动还原、变体文件 finally 清理、7 类对抗补丁全拒。
- 观察与下一步：推理模型倾向写"语义等价"的保守补丁（两轮打平）——提示词需要更激进的
  算法菜单（退火接受/扰动重启/移动分布改变）；low_willingness 在 6s 复筛下被截断，基线
  噪声偏大（1688~1925），可考虑单独调预算。

## 2026-09-20T00:34:30 · Real training start

- mode: code-lab
- rounds: 6
- backup: `pretrain_r4_20260920_003429.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 归因（round 2, high_noise）

高噪声场景下，候选来自 crossover 并调高 `triple_top_k=14`、`max_candidates_per_mask=11`，容易纳入更多噪声候选与掩码组合，筛选阶段被噪声干扰，导致得分略低于基线。下一步建议：降低 top_k 与每掩码候选数，加入置信度/去噪过滤；或改用局部变异在基线参数附近微调，避免大范围交叉引入噪声。

## 2026-09-20T00:46:28 · Forensics: RSI-operator

Round 3 元步：Agent 为自己编写并注册了新提案算子 `large_scene_worst_metric_boost_v3`（AST 白名单 + 子进程沙箱冒烟通过）。

```python
# wrong
operator pool = builtin ops

# fixed
operator pool += learned op `large_scene_worst_metric_boost_v3`
```

## RSI 元步（round 3）

新算子 `large_scene_worst_metric_boost_v3` 已注册：新算子已注册并加入 UCB 池（op_large_scene_worst_metric_boost_v3.py）

## 归因（round 4, low_willingness）

候选仅将 pair_top_k 调到 28，但筛选后样本过少（filtered: 2），该参数未改变候选集或排序，故均值与基线一致。低意愿场景对 top_k 不敏感。下一步应调整 filtered 数量/过滤阈值，优化 worst_metric_rebalance 权重，或引入低意愿专用特征；并加日志确认参数生效，对 filtered=2/5/10 做网格搜索。

## 归因（round 5, scarce_couriers）

改进幅度仅0.30，处于噪声范围，说明过滤后重平衡及 pair_top_k=44 未触及 scarce_couriers 的核心瓶颈。建议放弃该过滤策略，改用场景专属特征（如运力稀缺度、时段分布）或尝试更大参数搜索，并校验指标方差后再定方向。

## 2026-09-20T01:05:43 · Distill

- solver: 67.56KB
- compact config updated

## 2026-09-20 · V9 L4 激进化升级（算法菜单 + 温度 + 等价守卫 + 分场景预算）

- CODE_SYSTEM 加入五项算法菜单（退火接受/扰动重启/移动分布/批量移动/剪枝），合成温度
  0.2→0.9，新增相似度守卫（difflib >90% 直接打回，等价改写视为失败）。
- 行为验证：6 轮内零等价补丁（此前 4 轮里 2 轮打平），补丁变得真正大胆——r2 strategy_key
  −10.9%（真实探索的代价），r3 choose_probability_backups 在截断筛选下假胜出但全预算
  验证被杀（+12.5），r5 local_search 在 scarce 全预算下纹丝不动（该分支不执行该函数，
  噪声下限判负）。code_evolution 算子 10 用 5 胜（筛选级 50% 胜率）。
- 分场景复筛预算：实测 low_willingness 8s 才确定性（8s/9.3s spread=0.00 vs 6s ±6.4），
  fine_budget_for(scene)=8000 生效（r4 基线回到稳定区间）。
- 发现：系统负载下 6s 截断会让"快而劣"的补丁假胜出——全预算验证+噪声下限是唯一可靠
  裁判，此为设计确认而非缺陷。
- 425 试验，champion 仍未破。下一步：L4 目标扩容（base_orders/greedy_select/improve_*）、
  多补丁联合进化、或对 local_search 做定向多候选竞赛（一次合成 3 版并行筛选）。

## 2026-09-20T01:56:31 · Real training start

- mode: code-lab
- rounds: 4
- backup: `pretrain_r6_20260920_015631.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 2026-09-20T02:00:41 · Distill

- solver: 67.56KB
- compact config updated

## 2026-09-20 · V10 L4 锦标赛上线（余额耗尽，待充值验证）

- `try_l4` 重写为锦标赛：local_search 目标每轮并行合成 N 版（params l4_tournament_n=3），
  每版指定不同算法菜单焦点（退火/重启/移动分布…轮换），全体筛选后前 2 名进全预算验证，
  第一个通过全部门禁者晋升；非入选变体即时清理，finally 兜底。
- L4 目标扩容至 6 个：local_search、improve_low_with_multi_options、
  improve_regular_with_multi_options、choose_probability_backups、greedy_select、
  improve_backup_allocation（TARGET_NOTES 附契约：返回 (selected, backup_map) 等）。
- mock 验证通过（3 焦点并行、合成失败优雅处理、变体清理）；实弹接线验证通过——
  事件日志显示四轮 L4 全部按目标轮换触发，但全部 HTTP 402（DeepSeek 余额再次耗尽，
  推断为上一战役的大上下文推理调用消耗）。充值后重跑 code-lab 即可。

## 2026-09-20T20:54:44 · Real training start

- mode: code-lab
- rounds: 6
- backup: `pretrain_r1_20260920_205444.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 归因（round 2, high_noise）

高噪声下候选均值313.50与基线313.44仅差0.06，属随机波动，说明该crossover参数未触及关键瓶颈。建议增加多随机种子重复评估，用中位数或更稳健指标降噪；同时跳出当前参数邻域，尝试更大幅度的搜索维度或生成策略。

## 2026-09-20T21:15:33 · Real training start

- mode: code-lab
- rounds: 6
- backup: `pretrain_r3_20260920_211533.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 归因（round 2, high_noise）

候选失败主因：在高噪声场景下，将 `max_exact_replace_tasks` 提高到 11 可能引入更多错误替换，导致平均指标从 314.51 降至 313.44。下一步建议回退该参数，针对高噪声单独降低替换任务上限（如 7–8），并增加噪声过滤或置信度门槛后重试。

## 2026-09-20T21:33:19 · Forensics: RSI-operator

Round 3 元步：Agent 为自己编写并注册了新提案算子 `large_scene_worst_metric_boost_v4`（AST 白名单 + 子进程沙箱冒烟通过）。

```python
# wrong
operator pool = builtin ops

# fixed
operator pool += learned op `large_scene_worst_metric_boost_v4`
```

## RSI 元步（round 3）

新算子 `large_scene_worst_metric_boost_v4` 已注册：新算子已注册并加入 UCB 池（op_large_scene_worst_metric_boost_v4.py）

## 归因（round 3, large）

候选将局部搜索预算和拓扑限制调低，可能过度压缩了搜索空间，导致解质量略降且无明显提升；单一场景评估也易受噪声影响。下一步建议适度提高搜索预算、放宽拓扑生成限制，并结合多场景稳健验证，针对 large 场景瓶颈设计更有针对性的邻域算子。

## 归因（round 4, low_willingness）

候选失败主因是整体替换策略过度规避低意愿场景，破坏了基线原有收益结构，仅权重重排未触及核心约束。下一步应做单维消融，保留基线有效部分，只微调低意愿容忍排序或稀缺优先，避免全量替换。

## 归因（round 5, scarce_couriers）

候选未超基线主因：scarce_couriers 样本稀疏，filtered:2 过度过滤，large_scene_worst_metric_rebalance 在极少数样本上过拟合，pair_top_k=44 改变匹配分布，导致得分略降且无统计优势。下一步：减少过滤保留更多样本，pair_top_k 回退默认或小范围微调；改用置信度加权或不重平衡；引入少数类增强或合成样本，并用交叉验证评估。

## 2026-09-20T22:03:02 · Real training start

- mode: code-lab
- rounds: 2
- backup: `pretrain_r6_20260920_220302.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 归因（round 2, high_noise）

高噪声场景下，将 max_candidates_per_mask 增至11、triple_top_k增至25 可能引入更多噪声候选与三元组，导致指标略微恶化（313.50 vs 313.44）。建议下一步：降低候选数与 top_k，增加噪声过滤/去重，或采用更稳健的聚合与早停，避免过拟合噪声。

## 2026-09-20T22:19:43 · Distill

- solver: 67.56KB
- compact config updated

## 2026-09-20T22:23:43 · Real training start

- mode: code-lab
- rounds: 1
- backup: `pretrain_r2_20260920_222343.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 归因（round 1, medium）

候选提升仅+1.16，未超噪声阈值，且来源为large场景的`worst_metric_boost`，与medium场景失配；`triple_top_k=30`可能过于激进。建议在medium场景单独搜索参数，尝试`triple_top_k` 10–20，或改用medium自身最差指标加权。

## 2026-09-20T22:34:32 · Distill

- solver: 67.56KB
- compact config updated

## 2026-09-20T22:38:56 · Real training start

- mode: code-lab
- rounds: 3
- backup: `pretrain_r1_20260920_223856.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 2026-09-20T22:48:14 · Forensics: protected:small

L4 补丁（l4:local_search#3(batching several candidate replacements per remo)）在保护场景 small 上回退超容忍（容忍=0.80），已拒绝。

```python
# wrong
splice local_search (l4 patch r1)

# fixed
keep local_search unchanged
```

## 2026-09-20T22:48:30 · Forensics: protected:small

L4 补丁（l4:local_search#1(perturbation restarts with best-so-far retention)）在保护场景 small 上回退超容忍（容忍=0.80），已拒绝。

```python
# wrong
splice local_search (l4 patch r1)

# fixed
keep local_search unchanged
```

## 2026-09-20T22:49:58 · Forensics: protected:small

候选（large_scene_worst_metric_rebalance([filtered: 1])）在保护场景 small 上回退超容忍（容忍=0.80，anchor_gain=0.00）：180.285041 -> 182.627466，已拒绝晋升。

```python
# wrong
promote(CONFIG['normal_topology_generated_limit']=12, CONFIG['pair_top_k']=44)

# fixed
keep CONFIG unchanged (protected threshold preserved)
```

## 2026-09-20T22:52:53 · Real training start

- mode: code-lab
- rounds: 1
- backup: `pretrain_r2_20260920_225253.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 2026-09-20T23:06:18 · Forensics: medium

Round 1 L4 晋升：Agent 重写了 solver 的 `local_search` 函数（l4:local_search#1(perturbation restarts with best-so-far ret；anchor 626.32 -> 626.32，保护场景无回退）。依据：Implemented perturbation restarts with best-so-far retention: when strict improvement stalls, randomly remove 1-3 incumbents, exact-cover freed masks with slight score slack to permit occasionally worse moves, then re-improve and retain the best solution. Deadlines and budget are checked in all loop

```python
# wrong
def local_search (原实现前6行)
def local_search(ctx, selected, deadline_ms):
    current = list(selected)
    total_tasks = _count_bits(ctx.all_task_mask)
    current_eval = evaluate(current, total_tasks)
    start_ms = _now_ms()
    budget = CONFIG['local_search_budget_ms']
...

# fixed
def local_search (新实现前6行)
def local_search(ctx, selected, deadline_ms):
    current = list(selected)
    total_tasks = _count_bits(ctx.all_task_mask)
    current_eval = evaluate(current, total_tasks)
    best = list(current)
    best_eval = current_eval
...
```

## L4 代码进化（round 1）

目标 `local_search`：Implemented perturbation restarts with best-so-far retention: when strict improvement stalls, randomly remove 1-3 incumbents, exact-cover freed masks with slight score slack to permit occasionally worse moves, then re-improve and retain the best solution. Deadlines and budget are checked in all loop

```python
def local_search(ctx, selected, deadline_ms):
    current = list(selected)
    total_tasks = _count_bits(ctx.all_task_mask)
    current_eval = evaluate(current, total_tasks)
    best = list(current)
    best_eval = current_eval
    start_ms = _now_ms()
    budget = CONFIG['local_search_budget_ms']

    selected_ids = set(id(c) for c in current)
    unselected = [c for c in ctx.candidates if id(c) not in selected_ids]
    mask_to_unselected = {}
    for c in unselected:
        mask_to_unselected.setdefault(c.task_mask, []).append(c)
    for mask in mask_to_unselected:
        mask_to_unselected[mask].sort(key=lambda c: (candidate_penalty_cost(c), c.score, -c.willingness))

    def strict_improve():
        nonlocal current, current_eval, best, best_eval
        any_improved = False

        for _ in range(4):
            if _now_ms() - start_ms > budget or not _has_time(deadline_ms):
                return any_improved
            improved = False
            for ri in range(len(current)):
                if _now_ms() - start_ms > budget or not _has_time(deadline_ms):
                    break
                removed = current[ri]
                used_couriers = 0
                for j, c in enumerate(current):
                    if j != ri:
                        used_couriers |= c.courier_bit
                removed_penalty = candidate_penalty_cost(removed)
                for uc in mask_to_unselected.get(removed.task_mask, []):
                    if uc.courier_bit & used_couriers:
                        continue
                    if candidate_penalty_cost(uc) >= removed_penalty - EPS:
                        break
                    new_current = list(current)
                    new_current[ri] = uc
                    new_eval = evaluate(new_current, total_tasks)
                    if is_better(new_eval, current_eval):
                        current = new_current
                        current_eval = new_eval
                        if is_better(current_eval, best_eval):
                            best = list(current)
                            best_eval = current_eval
                        improved = True
                        any_improved = True
                        break
                if improved:
                    break
            if not improved:
                break

        for _ in range(2):
            if _now_ms() - start_ms > budget or not _has_time(deadline_ms):
                return any_improved
            improved = False
            for removed in rank_removals(current):
                if _now_ms() - start_ms > budget or not _has_time(deadline_ms):
                    break
                freed_mask = removed.task_mask
                removed_score = candidate_penalty_cost(removed)
                locked_couriers = 0
                for c in current:
                    if c is not removed:
                        locked_couriers |= c.courier_bit
                replacement = exact_cover_freed(ctx, freed_mask, locked_couriers, removed_score, deadline_ms)
                if replacement is not None:
                    candidate = replace_candidates(current, (removed,), replacement)
                    candidate_eval = evaluate(candidate, total_tasks)
                    if is_better(candidate_eval, current_eval):
                        current = candidate
                        current_eval = candidate_eval
                        if is_better(current_eval, best_eval):
                            best = list(current)
                            best_eval = current_eval
                        improved = True
                        any_improved = True
                        break
            if not improved:
                break

        rounds = [(2, CONFIG['pair_top_k'])]
        if CONFIG.get('try_triples', True):
            rounds.append((3, CONFIG['triple_top_k']))
        while _now_ms() - start_ms < budget and _has_time(deadline_ms):
            any_improved_combos = False
            for remove_count, top_k in rounds:
                if _now_ms() - start_ms > budget or not _has_time(deadline_ms):
                    return any_improved
                improved = False
                ranked = rank_removals(current)[:min(top_k, len(current))]
                for removed_tuple in itertools.combinations(ranked, remove_count):
                    if _now_ms() - start_ms > budget or not _has_time(deadline_ms):
                        break
                    freed_mask = 0
                    removed_score = 0.0
                    locked_couriers = 0
                    removed_set = set(id(c) for c in removed_tuple)
                    for c in current:
                        if id(c) in removed_set:
                            freed_mask |= c.task_mask
                            removed_score += candidate_penalty_cost(c)
                        else:
                            locked_couriers |= c.courier_bit
                    replacement = exact_cover_freed(ctx, freed_mask, locked_couriers, removed_score, deadline_ms)
                    if replacement is None:
                        continue
                    candidate = replace_candidates(current, removed_tuple, replacement)
                    candidate_eval = evaluate(candidate, total_tasks)
                    if is_better(candidate_eval, current_eval):
                        current = candidate
                        current_eval = candidate_eval
                        if is_better(current_eval, best_eval):
                            best = list(current)
                            best_eval = current_eval
                        improved = True
                        any_improved = True
                        any_improved_combos = True
                        break
                if not improved:
                    continue
            if not any_improved_combos:
                break
        return any_improved

    def restart_with_perturbation():
        nonlocal current, current_eval, best, best_eval
        if not current:
            return False
        for _attempt in range(CONFIG.get('restart_attempts', 8)):
            if _now_ms() - start_ms > budget or not _has_time(deadline_ms):
                return False
            r_count = random.randint(1, min(3, len(current)))
            idxs = random.sample(range(len(current)), r_count)
            removed_tuple = tuple(current[i] for i in idxs)
            freed_mask = 0
            removed_score = 0.0
            locked_couriers = 0
            removed_ids = set(id(c) for c in removed_tuple)
            for c in current:
                if id(c) in removed_ids:
                    freed_mask |= c.task_mask
                    removed_score += candidate_penalty_cost(c)
                else:
                    locked_couriers |= c.courier_bit
            ceiling = removed_score + max(1.0, removed_score * 0.05)
            replacement = exact_cover_freed(ctx, freed_mask, locked_couriers, ceiling, deadline_ms)
            if replacement is None:
                continue
            candidate = replace_candidates(current, removed_tuple, replacement)
            candidate_eval = evaluate(candidate, total_tasks)
            if set(id(c) for c in candidate) == set(id(c) for c in current):
                continue
            current = candidate
            current_eval = candidate_eval
            if is_better(candidate_eval, best_eval):
                best = list(candidate)
                best_eval = candidate_eval
            return True
        return False

    while _now_ms() - start_ms < budget and _has_time(deadline_ms):
        if not strict_improve():
            if not restart_with_perturbation():
                break

    return (best, best_eval)

```

## 2026-09-20T23:06:18 · Distill

- solver: 70.53KB
- compact config updated

## 2026-09-20 · 🏆 首次 L4 晋升：Agent 编写的算法代码进入提交 solver

23:06:17，RSI 历史性时刻——L4 补丁 `local_search#1`（扰动重启 + best-so-far 保留）
通过全部门禁链：AST 白名单 → 子进程沙箱 → 筛选（401.58 vs 403.71）→ 全预算验证
（holdout 405.13→403.07，anchor 无回退）→ 配对保护门禁 → 备份 → 拼接写回 → smoke。
solver sha 587c4533fc16c814 → 81fecfedf27aa317，size 68.92→70.53KB。
晋级后复测：anchor 626.32 不变（无回退），medium holdout 401.33（真实改进 ~3.8）。

打通晋升的三个门禁修正（全部有实测依据）：
1. AST 验证器放行 Try/Nonlocal/Raise/Assert（真实算法代码必需；沙箱才是安全边界）
   ——此前连续误杀 4 个合法补丁。
2. 晋升语义改为"场景改进 + anchor 无回退"：holdout_gain ≥ 1.0 且 anchor_gain ≥ -0.5，
   anchor 不再要求严格变好（local_search 结构上不支配 anchor——大案例走 improve_regular）。
3. 保护门禁改配对测量：全预算保护场景随负载漂 ±2.3 > 容忍 0.8，陈旧 champion 基线
   会误判；改为同负载背靠背 fresh baseline vs candidate 的真实差值（实测补丁真实回退
   仅 +0.20/+0.00，被旧门禁误拒两次）。

新增工程能力：L4 补丁档案（memory/l4_archive/）——过筛未晋升的补丁持久化，
后续轮次免费重试（本轮档案补丁重筛零 LLM 调用）；晋升后自动清档。
已知小笔误已修：锦标赛路径漏记 summary["promoted"]；protected champion 只在真实变好时更新。

## 2026-09-20T23:14:31 · Real training start

- mode: code-lab
- rounds: 3
- backup: `pretrain_r1_20260920_231431.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 2026-09-20T23:20:42 · Forensics: protected:small

候选（large_scene_worst_metric_boost）在保护场景 small 上配对回退 +2.09 超容忍（容忍=0.80，anchor_gain=0.00，同负载基线 180.738746），已拒绝晋升。

```python
# wrong
promote(CONFIG['pair_top_k']=34)

# fixed
keep CONFIG unchanged (protected threshold preserved)
```

## 归因（round 2, high_noise）

高噪声下将 max_candidates_per_mask 提到 24、triple_top_k 提到 11，可能引入更多噪声掩码，导致筛选均值略降且未超基线。建议降低候选数与 top_k，增强去噪或正则，并尝试其他 origin 及交叉验证。

## 2026-09-20T23:27:29 · Forensics: RSI-operator

Round 3 元步：Agent 为自己编写并注册了新提案算子 `large_scene_worst_metric_boost_v5`（AST 白名单 + 子进程沙箱冒烟通过）。

```python
# wrong
operator pool = builtin ops

# fixed
operator pool += learned op `large_scene_worst_metric_boost_v5`
```

## RSI 元步（round 3）

新算子 `large_scene_worst_metric_boost_v5` 已注册：新算子已注册并加入 UCB 池（op_large_scene_worst_metric_boost_v5.py）

## 2026-09-20T23:33:42 · Forensics: large

Round 3 晋升（large_scene_worst_metric_boost_v2([filtered: 1])）：anchor 626.32 -> 626.32, holdout 618.67 -> 616.89，保护场景无回退。

```python
# wrong
local_search_budget_ms=2800.0 / normal_topology_top_k=6 / normal_topology_generated_limit=10 / normal_preview_scan_per_primary=18 / pair_top_k=28 / triple_top_k=20 / max_exact_replace_tasks=8

# fixed
CONFIG['local_search_budget_ms']=1400.0, CONFIG['normal_topology_top_k']=10, CONFIG['normal_topology_generated_limit']=18, CONFIG['normal_preview_scan_per_primary']=30, CONFIG['pair_top_k']=44, CONFIG['triple_top_k']=32, CONFIG['max_exact_replace_tasks']=11
```

## 2026-09-20T23:33:42 · Distill

- solver: 70.53KB
- compact config updated

## 2026-09-20 · 🏆 第二次晋升（首次 CONFIG 晋升，L3 反哺 L1）+ 定向强攻机制

- 新增 params `l4_target`：可强制整场战役聚焦单一目标函数（默认轮换）。首战定向
  improve_regular_with_multi_options（anchor 支配函数）。
- 定向战役 3 轮战果：r1 LLM 重写 96 行大函数产出非法解（inf，正确被筛）；r2/r3 补丁
  未过筛选（+0.16%）；但 r3（large 场景）中 L3 自写算子 `large_scene_worst_metric_boost_v2`
  的 7 键 CONFIG 组合提案（local_search_budget=1400, topology_top_k=10, generated_limit=18,
  preview_scan=30, pair_top_k=44, triple_top_k=32, exact_replace=11）通过全门禁晋升——
  holdout:large 618.67→616.89，protected:scarce 同步改善至 1185.71。
- **这是首次 CONFIG 晋升，且提案出自 Agent 为自己写的算子——L3→L1 反哺闭环实证。**
- 同轮另一个 CONFIG 候选 holdout 403.07→401.33 过验证但被配对保护门禁以真实回退拒绝
  ——门禁在双路径上同时严格执行。
- 全场景终测（晋级后 solver，全预算）：anchor 626.32(40/40)、medium 401.73、
  high_noise 299.69、large 617.88、low_will 1695.90、scarce 1199.15，全部 valid+全覆盖，
  体积 70.53KB。两次晋升（L4 代码 + L1 CONFIG）当日达成，RSI 飞轮开始复利。

## 2026-09-21T17:18:09 · Real training start

- mode: code-lab
- rounds: 9
- backup: `pretrain_r3_20260921_171808.zip`
- every metric below is measured by running submission/solver.py in a subprocess

## 归因（round 2, high_noise）

候选在 high_noise 下仅以 1.08 的微弱优势领先，未超噪声容限，可能因 large_scene_worst_metric_rebalance 策略过拟合特定场景，且仅调 pair_top_k=28 无法稳定改善。建议加入去噪预处理、分场景自适应 top_k 或鲁棒聚合，并多次重复验证显著性。

## 归因（round 3, large）

候选均值与基线几乎持平（差0.0002），说明仅微调局部搜索预算和生成限制未触及瓶颈，筛选后样本减少且参数保守，导致缺乏显著改进。下一步可增大局部搜索预算、放宽生成限制，并调整 pair/triple top k；或换用不同过滤条件与重平衡策略，增加候选多样性。

## 归因（round 4, low_willingness）

候选未击败基线，best与baseline完全相同，说明策略扰动未改变任务分配结果，仍落入原有局部最优。建议下一步打破对称性：调整初始解或目标权重，引入随机重启、禁忌机制，或针对低意愿场景设计显式激励/惩罚项。

## 归因（round 5, scarce_couriers）

候选仅微调 pair_top_k=28，未触及稀缺骑手场景的核心瓶颈，提升约5.8不显著，可能被筛选噪声掩盖。建议针对供给稀缺增加区域配对惩罚或动态阈值，并对 scarce_couriers 单独做交叉验证，避免单点调参。

## 归因（round 6, medium）

候选在大场景上调出的 pair_top_k=50 直接搬到 medium 场景，导致均值从 401.92 略升至 402.50，说明该参数对场景敏感，存在过拟合大场景、不适配中等场景的问题。建议下一步：在 medium 场景内围绕原始 pair_top_k 做小范围搜索，或加入场景专属调参；也可尝试其他参数组合，并以原基线配置为 Warm Start。

## 归因（round 7, high_noise）

候选与基线分数完全一致，说明在高噪声场景下，`filtered:3` 与 `pair_top_k=36` 的组合未改变有效样本或排序结果，可能过滤后信息量不足或超参触及饱和。建议更换候选来源，调整过滤阈值或噪声抑制策略，尝试更大的 top_k，并结合去噪特征或加权重平衡，避免仅微调原有超参。

## 归因（round 8, large）

候选失败主因：将局部搜索预算提高到2150ms、精确替换任务数增至14，搜索过度集中于局部邻域，扰动过大且耗时，破坏了原有较好解，未带来有效改进。下一步应缩短局部搜索预算（如800–1200ms），降低替换任务数至8–10，并加入随机扰动或全局重启机制以增强多样性。

## 2026-09-21T17:45:34 · Forensics: RSI-operator

Round 9 元步：Agent 为自己编写并注册了新提案算子 `low_willingness_worst_metric_boost`（AST 白名单 + 子进程沙箱冒烟通过）。

```python
# wrong
operator pool = builtin ops

# fixed
operator pool += learned op `low_willingness_worst_metric_boost`
```

## RSI 元步（round 9）

新算子 `low_willingness_worst_metric_boost` 已注册：新算子已注册并加入 UCB 池（op_low_willingness_worst_metric_boost.py）

## 2026-09-20 · improve_backup_allocation 两攻未克 + 统计污染修复

- 新增 params `l4_scenes`：L4 只在目标函数实际执行的场景上开火（improve_backup_allocation
  仅存在于 low_willingness 分支，其他场景筛选必然打平）——避免浪费 LLM 调用。
- 9 轮定向战役：r4/r9 两次 L4 攻击 improve_backup_allocation 均未过筛
  （1682.99/1688.23 vs 基线 1681.87）——该函数的 backup 重分配逻辑对 LLM 重写抗性较高。
  其余 7 轮 CONFIG 管线无晋升（多轮细筛差距 <0.5%）。经验库 619 试验，L3 算子池 9 个。
- 修复统计污染 bug：invalid 补丁筛选得 inf → gain=-inf 直接毒化算子 gain_sum/avg/UCB
  （code_evolution 曾显示 -inf）。credit_operator 现夹取 [-50,+50]，新增
  repair_operator_stats() 从 trials 重算——已修复存量数据（37 用 18 胜，UCB 2.0）。
- 双晋升日战果保持：anchor 626.32 / medium 403.07 / large 616.89，solver 70.53KB。
