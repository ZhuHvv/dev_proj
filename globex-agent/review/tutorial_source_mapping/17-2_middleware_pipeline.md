# 17-2 Middleware-Hook-Pipeline与工具调用生命周期

> [钉钉原文](https://docs.dingtalk.com/i/nodes/yQod3RxJKGkMNXZ5hoZX9qkqJkb4Mw9r) · 当前结论：**使用 AgentScope Middleware 做等价实现**。

## 当前源码对应

[harness_middleware.py](../../app/infrastructure/harness_middleware.py) 与 [resilience.py](../../app/infrastructure/resilience.py) 都实现 AgentScope `ToolMiddlewareBase`；工具在各 Factory 的 `build_tools()` 中注册。

## 生命周期

模型产生 ToolCall → [Harness middleware](../../app/infrastructure/harness_middleware.py#L43) 外层 before → [schema/sequencing 断言](../../app/application/harness/assertions.py#L63) / [loop 检测](../../app/application/harness/loop_detector.py#L66) → [resilience allow/timeout/retry](../../app/infrastructure/resilience.py#L97) → Python 工具函数 → UseCase/外部依赖 → resilience 记账 → Harness after 检查 → `ToolChunk` → 模型。

中间件是洋葱结构：外层先进入、后退出。注册顺序会决定 Harness 看到的是原始异常、重试后的结果还是已经转成 `[error]` 的 ToolChunk。

## 数据与副作用

before 阶段应在写操作前阻断非法参数/顺序；after 阶段可验证结果 schema 和语义。超时不代表下游一定没有完成，订单工具仍需幂等键或事务边界。

## 与教程的差异

本仓没有单独自建 Hook Registry/Pipeline 框架，而是复用 AgentScope 中间件。概念可以一一映射，但实际覆盖范围必须按最终 Toolkit 接线核对，参见 [17-1](17-1_harness_mapping.md)。
