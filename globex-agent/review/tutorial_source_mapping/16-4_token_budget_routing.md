# 16-4 Token预算管理与模型路由降级

> [钉钉原文](https://docs.dingtalk.com/i/nodes/b9Y4gmKWrPjda5OKt4Ny09wZJGXn6lpz) · 当前结论：**部分落地**。

## 当前源码对应

[budget.py](../../app/infrastructure/budget.py) 维护每轮 token 预算与剩余额度；[llm.py](../../app/infrastructure/llm.py) 在模型调用前收费/判断层级并选择主模型或便宜模型；Agent 中间件还可要求回复更简洁。

## 真实决策链

[Orchestrator 初始化本轮状态](../../app/application/agents/orchestrator.py#L140) → [TokenBudget](../../app/infrastructure/budget.py#L49) → [每次 ThrottledChatModel 调用](../../app/infrastructure/llm.py#L59) → `main/lite/minimal` 档位 → [上游/模型降级决策](../../app/infrastructure/llm.py#L94) 或 [fallback](../../app/infrastructure/llm.py#L133) → [扣减消耗](../../app/infrastructure/llm.py#L190) → 后续调用继续基于剩余量路由。

## 数据与副作用

预算是请求/会话内工程状态，不改变业务数据；它会改变模型、最大输出和回答质量。模型失败还可能触发 fallback，从而增加一次外部调用和延迟。

## 关键差异

`budget.py` 的设计说明提到极低余额可完全不调 LLM，但当前 [llm.py](../../app/infrastructure/llm.py) 仍可能选择便宜模型；仓库没有确定性的“规则回复器”。因此 `<5% 完全零模型调用` 不能作为已实现事实。

## 验证

测试应覆盖边界值、连续工具轮次、fallback 二次收费与并发隔离，并在事件/trace 中记录实际模型和预算档位。
