# RSD-Marvis AutoSolver Studio V5 HARD FIX

这是严格按照 9 条要求重新生成的修复版。重点是“可见、可点、可训练、可回滚”。

## V6 RSI：递归自改进（真正的 Agent）

V5.1 把假训练换成了真实测量循环；V6 在其上实现了三层递归自改进（RSI）：

```
L1  solver 自身改进     CONFIG 变异 → 全预算验证 → 保护场景门禁 → 写回 solver.py
L2  改进"改进策略"      sqlite 经验库 + UCB1 bandit 提案算子池（哪个算子常胜就多用谁）
L3  Agent 给自己写代码  每 3 轮元步：LLM 写出新算子 mutate_config()
                        → AST 白名单验证 → 子进程沙箱冒烟 → 自动加入 UCB 池
```

- **经验库** `agent_core/experience.py`：每次筛选试验连同其来源算子入库；胜算子加权、
  胜出 CONFIG 键做杠杆分析（leverage）反哺 proposal。
- **算子池** `agent_core/operators.py`：5 个内置算子 + 学习算子，UCB1 排序调用；
  llm_propose 与学习算子有优先席位（防 UCB 饥饿）。
- **代码合成** `agent_core/code_synthesis.py`：静态 AST 白名单（禁 import/IO/eval/危险属性）+
  8s 硬超时子进程沙箱 + 提案白名单，三关全过才注册；无 API key 时自动跳过，L1/L2 照常运行。
- **两阶段筛选**：2s 粗筛全部候选 → 前 2 名以 5s 复筛（更接近 9.3s 全预算行为），
  决策以复筛为准；细筛通过门槛 0.5%，全预算验证才是真门禁。
- **自适应保护门禁**（params.json global）：`regression_tolerance`（默认 0.5）、
  `anchor_tradeoff_ratio`（默认 0，>0 时 anchor 收益可按比例换取保护容忍，上限
  `anchor_tradeoff_cap`）、`anchor_tradeoff_cap`。被门禁拒绝且 anchor 改进 ≥2 分时，
  Auditor 会提示可开启 tradeoff。
- **RSI 面板**：训练页新增三层状态卡片 + 算子榜（使用/胜出/UCB，L3 学习算子高亮）。
- **LLM 错误透明化**：API 失败原因（如 402 Payment Required）会出现在元步事件里，
  不再误报为"格式问题"。

## V5.1 架构升级：真实训练循环（agent_core）

V5 hardfix 的“一键训练”是**演示假循环**（每轮 gain 为硬编码 + sleep，从不运行 solver）。
V5.1 新增 `agent_core/` 包，把训练替换为真实的 测量→变异→筛选→验证→门禁→晋升/回滚 循环：

| 模块 | 职责 |
|------|------|
| `agent_core/evaluator.py` | 官方口径评分器（合法性、覆盖率、期望罚分），移植自比赛 agent 框架 |
| `agent_core/runner.py` + `solver_worker.py` | 子进程隔离运行 `submission/solver.py`（可硬杀超时，CONFIG 覆盖白名单校验） |
| `agent_core/case_bank.py` | 场景真实（scene-true）案例库：medium/high_noise 为 30 任务、low_willingness 压 willingness、scarce 压骑手比，确保命中 solver 内部 `configure_runtime` 的对应分支 |
| `agent_core/mutations.py` | 只在 `apply_runtime_overrides` 覆盖后仍生效的 CONFIG 键上变异，全部带边界白名单 |
| `agent_core/config_io.py` | 外科手术式改写 solver.py 第 6 行 CONFIG 字面量（ast 定位，写前 compile 检查，可字节级恢复） |
| `agent_core/llm.py` | LLM 只做两件事：结构化 CONFIG 提案（过白名单）、失败归因文本；无 key 时自动退化为确定性搜索 |
| `agent_core/trainer.py` | 一键训练主循环：筛选(3s 预算) → 全预算验证(anchor+holdout 双改进) → 保护场景无回退门禁 → 备份后晋升 + smoke 验证 |

每轮的训练数字都是**实测值**（旧版 current_state.json 中的 716.74/675.35 等为占位数据，
实测 anchor 全预算 penalty ≈ 626.3，40/40 覆盖，见 champion.measured）。

## 启动

```powershell
cd rsd_marvis_autosolver_studio_v5_hardfix
python app.py
```

打开：

```text
http://127.0.0.1:8765
```

## 界面功能（沿用 V5 hardfix）

- 左侧第二项：`🚀 一键训练`
- 顶部第一按钮：`🚀 启动一键训练`
- Cockpit 默认出现：柱状图、折线图、雷达图、热力图、场景地图
- 新增模块：训练日志、一键回滚
- Agent 和 Flow 节点均可点击展开详情
- DataLab 可编辑参数并保存
- 训练前自动备份，回滚需要输入 `ROLLBACK`
- 新增控制台按钮语义：`evaluate`（实测 anchor 并写入 champion.measured）、`ensure_cases`（重建案例库）

## 训练时长参考

- 每轮：筛选基线 + 3~4 个候选（各 2 案例 @3s 预算）≈ 30~40s；触发验证再加 ~20s，触发门禁再加 ~30s
- 首轮会额外建立 champion 基线（anchor + holdout，全预算 ~10s/案例）
- 6 轮 balanced 约 5~8 分钟；训练可随时中止（案例之间响应 STOP）

## DeepSeek

不要把 API Key 写入代码：

```powershell
$env:DEEPSEEK_API_KEY="你的新 key"
$env:DEEPSEEK_BASE_URL="https://api.deepseek.com"
$env:DEEPSEEK_MODEL="deepseek-v4-pro"
```

未设置 key 时训练照常运行（确定性变异搜索），仅 LLM 提案与归因跳过。

