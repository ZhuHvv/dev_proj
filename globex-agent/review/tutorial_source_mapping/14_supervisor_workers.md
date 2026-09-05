# 14 主AgentLoop组装与Supervisor-Workers协同机制

> [钉钉原文](https://docs.dingtalk.com/i/nodes/9E05BDRVQ2aGym04UDax3nmvJ63zgkYA) · 当前结论：**等价落地**。

## 角色映射

教程的 Supervisor 对应 [main_agent.py](../../app/application/agents/main_agent.py) 创建的 MainAgent；Workers 对应 [search_agent.py](../../app/application/agents/search_agent.py) 与 [trade_agent.py](../../app/application/agents/trade_agent.py)；协同入口是 [task_dispatch_tool.py](../../app/application/tools/task_dispatch_tool.py)。

## 真实协同链

[MainAgent 工具集](../../app/application/agents/main_agent.py#L106) 拆解复杂意图 → `TaskCreate/TaskUpdate` 记录计划 → [task_dispatch(subagent_type, demands)](../../app/application/tools/task_dispatch_tool.py#L73) → [按次创建 SearchAgent](../../app/application/agents/search_agent.py#L84) / [TradeAgent](../../app/application/agents/trade_agent.py#L79) → 子 Agent 调业务工具并返回总结 → MainAgent 更新 Task/合并答案 → [Orchestrator 推送最终流](../../app/application/agents/orchestrator.py#L329)。

## 状态与副作用

- MainAgent 及其 `tasks_context` 随 session 保存；子 Agent 是按派发临时创建，不拥有独立长期 session。
- SearchAgent 主要读检索数据；TradeAgent 可创建/取消订单，具有业务副作用。
- 子 Agent 回答是 MainAgent 的 observation，不直接替代最终答复。

## 并行与失败

[verify_parallel.py](../../scripts/verify_parallel.py) 用于验证可并行派发，但实际是否并发仍由模型计划与框架执行决定。单个 worker 失败会成为工具错误，MainAgent 可重试、改派或降级；不是传统常驻 worker 池。

## 与教程的差异

MainAgent 也直接拥有所有业务工具，Supervisor-Workers 是按复杂度选择的协作模式，不是强制层级路由。
