# 03-0 主AgentLoop按需派发子Agent的策略与三件事判断

> [钉钉原文](https://docs.dingtalk.com/i/nodes/QPGYqjpJYr3Yd94kIB5e47Yj8akx1Z5N) · 当前结论：**已落地，但属于 Prompt 软路由**。

## 三件事判断的源码位置

派发准则写在 [globex.yml](../../app/application/prompts/globex.yml) 的主 Agent 系统提示词中；执行入口是 [task_dispatch_tool.py](../../app/application/tools/task_dispatch_tool.py) 的 `task_dispatch()`。MainAgent 同时持有直接业务工具与派发工具，因此模型可以选择“自己做”或“交给子 Agent”。

## 真实调用链

[MainAgent 工具集](../../app/application/agents/main_agent.py#L106) → 模型依据 [派发 Prompt 规则](../../app/application/prompts/globex.yml#L51) 判断复杂度 → `TaskCreate/TaskUpdate` → [task_dispatch(agent=search|trade)](../../app/application/tools/task_dispatch_tool.py#L73) → [创建 SearchAgent](../../app/application/agents/search_agent.py#L84) 或 [TradeAgent](../../app/application/agents/trade_agent.py#L79) → 子 Agent 结果回主 Agent → [Orchestrator 输出最终流](../../app/application/agents/orchestrator.py#L329)。

## 数据与副作用

- Task 状态保存在 AgentScope 的 `tasks_context`，派发事件由 `TradeEventBus` 发给前端。
- 每次派发新建子 Agent，子 Agent 本身不跨请求持久化；MainAgent 的 session 状态会持久化。
- TradeAgent 可触发下单/取消的真实写操作，所以派发不仅是“并发计算”。

## 异常与差异

Python 中没有一个确定性的“三件事分类器”；路由依赖模型遵循 Prompt。派发失败会以工具错误回到 MainAgent，由主 Agent 决定解释、重试或降级。若需要强保证，应增加服务端规则与派发集成测试，而不能只改提示词。
