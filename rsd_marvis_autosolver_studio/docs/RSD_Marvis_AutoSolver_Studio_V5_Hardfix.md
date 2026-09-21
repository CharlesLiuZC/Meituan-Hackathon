# RSD-Marvis AutoSolver Studio V5 HARD FIX

这是严格按照 9 条要求重新生成的修复版。重点是“可见、可点、可训练、可回滚”。

## 启动

```powershell
cd rsd_marvis_autosolver_studio_v5_hardfix
python app.py
```

打开：

```text
http://127.0.0.1:8765
```

## 必须能看到的变化

- 左侧第二项：`🚀 一键训练`
- 顶部第一按钮：`🚀 启动一键训练`
- Cockpit 默认出现：柱状图、折线图、雷达图、热力图、场景地图
- 新增模块：训练日志、一键回滚
- Agent 和 Flow 节点均可点击展开详情
- DataLab 可编辑参数并保存
- 训练前自动备份，回滚需要输入 `ROLLBACK`

## 当前 solver

- size: 68.92 KB
- functions: 45
- classes: 3

## DeepSeek

不要把 API Key 写入代码：

```powershell
$env:DEEPSEEK_API_KEY="你的新 key"
$env:DEEPSEEK_BASE_URL="https://api.deepseek.com"
$env:DEEPSEEK_MODEL="deepseek-v4-pro"
```
