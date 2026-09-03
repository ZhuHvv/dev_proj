# 03-1 技术栈与多Agent架构选型

> [钉钉原文](https://docs.dingtalk.com/i/nodes/P0MALyR8klKwN5RPUYgpaZ6bW3bzYmDO) · 当前结论：**实现已改线**。

## 当前技术栈事实

依赖版本以 [pyproject.toml](../../pyproject.toml) 为准；当前核心是 AgentScope 2.x、FastAPI、Redis、Qdrant、SQL 存储和 React。组装入口是 [composition.py](../../app/composition.py)，不是教程早期方案中的 LangChain/LangGraph 图。

## 当前多 Agent 形态

```text
MainAgent（Supervisor）
├─ 直接注册 Search/Trade 业务工具
├─ Task* 规划工具
└─ task_dispatch
   ├─ SearchAgent（按次创建）
   └─ TradeAgent（按次创建）
```

`MainAgentFactory.build()` 决定主 Agent 工具集；[task_dispatch_tool.py](../../app/application/tools/task_dispatch_tool.py) 决定子 Agent 创建与调用；[orchestrator.py](../../app/application/agents/orchestrator.py) 管理请求生命周期和状态落盘。

## 选型带来的边界

- 优点：复用 AgentScope 的 ReAct、Toolkit、Task 与状态模型，代码重点落在业务端口和工程治理。
- 代价：路由、确认和很多行为是 Prompt 软约束；框架内部循环不在本仓显式可见。
- 教程中的其他框架可用于理解取舍，但不能用其 API 名称推断当前代码。

## 阅读建议

依次读 `pyproject.toml → composition.py → main_agent.py → task_dispatch_tool.py → search_agent.py/trade_agent.py`，再看 [设计演进记录](../设计演进记录.md) 了解方案变化。
