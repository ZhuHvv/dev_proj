# 08 Rubric评测与Agentic-RL训练闭环

> [钉钉原文](https://docs.dingtalk.com/i/nodes/X6GRezwJlArL250wig2pdNOe8dqbropQ) · 当前结论：**Rubric 评测底座已落地，Agentic RL 训练闭环未落地**。

## 当前源码对应

[eval/cases.yaml](../../eval/cases.yaml) 定义回归样例和分级要求；[eval_regression.py](../../scripts/eval_regression.py) 运行案例、收集轨迹并调用 LLM Judge；报告按 P0/P1/P2 Rubric（评分准则）给出门禁结果。

## 真实评测链路

[构造 Ground Truth/Rubric](../../scripts/eval_regression.py#L54) → [逐 case 调用 Globex 主链](../../scripts/eval_regression.py#L134) → 收集最终答复/工具轨迹 → 规则与 LLM Judge 评分 → [渲染聚合报告](../../scripts/eval_regression.py#L168) → 质量门禁。这里评价的是 Agent 行为与最终结果，不只比较字符串。

## 数据、副作用与失败

- 输入是人工维护的案例、期望事实和 Rubric；输出是离线报告，不修改在线业务数据。
- Judge 本身有模型随机性和费用，关键 P0 条件仍应有确定性断言。
- 外部模型、服务或种子数据变化可能导致基线漂移，因此报告需记录模型和 Prompt 指纹。

## 与教程的差异

本仓没有把 bad case 自动转成训练样本，也没有 reward 计算、RL 训练、checkpoint 注册和灰度晋级。现状是“可产生训练信号的评测床”，不是闭环训练系统。
