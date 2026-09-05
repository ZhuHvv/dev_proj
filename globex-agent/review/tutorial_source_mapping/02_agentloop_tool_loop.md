# 02 AgentLoop快速入门与多轮工具调用

> [钉钉原文](https://docs.dingtalk.com/i/nodes/1OQX0akWmxvLXAb5Uby59n6X8GlDd3mE) · 当前结论：**已落地**。

## 教程概念落到哪里

MainAgent 在 [main_agent.py](../../app/application/agents/main_agent.py) 中设置较大的 `max_iters`，SearchAgent 与 TradeAgent 在各自工厂中使用更小上限；工具由 `Toolkit` 注册，Python 函数签名和 docstring 生成可供模型调用的 schema。

## 多轮为什么会发生

[MainAgent 构建与工具注册](../../app/application/agents/main_agent.py#L106) → 框架生成 `tool_call` → [SearchAgent 工具工厂](../../app/application/agents/search_agent.py#L57) 或 [TradeAgent 工具工厂](../../app/application/agents/trade_agent.py#L61) → `ToolChunk` 作为 observation 回到模型 → [Orchestrator 消费下一轮流式事件](../../app/application/agents/orchestrator.py#L329)。例如商品条件不充分时可能先检索，再根据候选继续品类洞察；复杂交易任务也可先创建 Task，再 [派发子 Agent](../../app/application/tools/task_dispatch_tool.py#L73)。

关键文件：[main_agent.py](../../app/application/agents/main_agent.py)、[search_agent.py](../../app/application/agents/search_agent.py)、[trade_agent.py](../../app/application/agents/trade_agent.py)、[orchestrator.py](../../app/application/agents/orchestrator.py)。

## 数据、副作用与失败路径

- 每次工具结果进入当前 Agent 上下文，可能增加 token 消耗并触发上下文压缩。
- 业务副作用取决于工具：检索只读，订单和偏好工具会写数据。
- `max_iters` 是配置的循环上限；Harness 的 LoopDetector 命中后追加收敛提示，不直接停止调用，且受实际中间件接线范围限制，见 [17-1](17-1_harness_mapping.md)。

## 与教程的差异

本仓没有用示例代码显式实现每轮循环；多轮调度由 AgentScope 完成。要验证真实轮次，应看 `tool.invoke/tool.result/token.delta` 事件，而不是仅看最终回复。
