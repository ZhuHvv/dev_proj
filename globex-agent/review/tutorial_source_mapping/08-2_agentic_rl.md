# 08-2 Agentic RL 训练全流程

> [钉钉原文](https://docs.dingtalk.com/i/nodes/ZQYprEoWonDwOA3lUB744jDb81waOeDk) · 当前结论：**训练侧内容，当前仓库未落地 RL**。

## 本仓能提供什么

[eval_regression.py](../../scripts/eval_regression.py) 的 Rubric 分数、工具调用轨迹、错误类别和最终结果可作为未来 reward（奖励信号）候选；[metrics.py](../../scripts/eval/metrics.py) 提供检索侧确定性指标；ConversationStore 可保留运行轨迹。

## 教程闭环映射

`环境/任务 → Agent rollout → 工具与业务环境返回 observation → Rubric/规则形成 reward → 外部 RL 优化 → 新模型版本 → 离线回归 → 灰度上线`。

在线 Globex 可以充当“环境适配和评测端”，但训练执行应在独立训练基础设施中完成；不能把 `llm.py` 的推理调用误认为训练。

## 缺失组件

当前检索范围内没有 rollout worker、reward model、advantage 计算、PPO/GRPO 等优化器、checkpoint、模型注册与晋级控制器。

## 安全边界

交易写操作不能在真实生产环境里自由 rollout；应使用可重置沙箱、模拟订单仓库和强规则奖励。RL 也不能学习绕过确认、权限或内容护栏。
