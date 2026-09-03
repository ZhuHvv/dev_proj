# 01 AgentLoop范式与电商搜索Agent核心概念

> [钉钉原文](https://docs.dingtalk.com/i/nodes/R4GpnMqJzGalZrjNhkz4d7498Ke0xjE3) · 当前结论：**等价落地**。循环由 AgentScope 2.x 承担，本仓负责工具、上下文和事件边界。

## 教程概念落到哪里

| 教程概念 | 当前源码 |
| --- | --- |
| Agent 与 ReAct 循环 | [main_agent.py](../../app/application/agents/main_agent.py) 的 `MainAgentFactory.build()` 与 `ReActConfig` |
| 流式消费循环 | [orchestrator.py](../../app/application/agents/orchestrator.py) 的 `_consume_reply()` |
| 搜索工具集合 | [search_agent.py](../../app/application/agents/search_agent.py) 的 `build_tools()` |
| 用户请求入口 | [server.py](../../app/presentation/server.py) 的 `submit_intent()` |

## 真实调用链

[HTTP 提交意图](../../app/presentation/server.py#L131) → [Orchestrator 处理一轮请求](../../app/application/agents/orchestrator.py#L140) → [恢复或创建 session Agent](../../app/application/agents/main_agent.py#L171) → [消费 Agent 流式回复](../../app/application/agents/orchestrator.py#L329) → [已注册的搜索/交易工具](../../app/application/agents/main_agent.py#L106) → `ToolChunk` 回到框架循环 → [发布业务事件](../../app/infrastructure/eventbus.py#L107)。

教程里的 Think/Act/Observe（思考/行动/观察）不是仓库中的三个 Python 函数；它们在 AgentScope 的 `ReActAgent` 内部发生。仓库可观察的边界是：输入如何构造、工具如何注册、工具结果怎样回注、流式事件如何转发。

## 数据、副作用与异常

- 对话状态进入 `AgentState.context/summary/tasks_context`，轮末由 `SessionRegistry.persist()` 保存。
- 商品搜索只读；下单/取消会修改订单和库存；偏好工具会写长期存储。
- 工具错误通常转成 `[error]` 类型的 `ToolChunk` 交给模型解释；顶层异常由 Orchestrator 发布 `error` 事件并走 `finally` 清理上下文。

## 与教程的差异

教程讲的是通用 AgentLoop 范式；当前实现不是手写 `while` 循环，也不是早期 LangChain/LangGraph 路线。阅读时先看本仓接线，再把框架内部循环当作依赖实现。
