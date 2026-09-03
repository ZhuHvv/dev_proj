# 17-1 Harness工程全景与Globex组件映射

> [钉钉原文](https://docs.dingtalk.com/i/nodes/yQod3RxJKGkMNXZ5hoZXeL5pJkb4Mw9r) · 当前结论：**组件部分落地，但当前业务工具接线不完整**。

## 组件映射

`app/application/harness/` 包含 schema、sequencing、loop 与 drift 检测；[harness_middleware.py](../../app/infrastructure/harness_middleware.py) 把断言包成 AgentScope 工具中间件；[resilience.py](../../app/infrastructure/resilience.py) 负责超时/重试/熔断。

## 设计链路

理想路径：ToolCall → [Harness middleware pre/post](../../app/infrastructure/harness_middleware.py#L43) → [Resilience middleware](../../app/infrastructure/resilience.py#L97) → Tool → Harness post-check → [EventBus 事件/违规](../../app/infrastructure/eventbus.py#L107)。

## 当前实际接线差异

`MainAgentFactory._resilience()` 虽构造 Harness + Resilience 链，但 MainAgent 直接复用 `SearchAgentFactory.build_tools()` 和 `TradeAgentFactory.build_tools()` 的业务工具；这些工具内部只挂了 `ToolResilienceMiddleware`。当前 Harness 链直接传给 `task_dispatch`、remember、forget，并未覆盖 product/category/order 全部业务工具。

## 为什么这个差异重要

目录中“有 Harness 类”和测试单独挂载成功，不等于生产 Toolkit 已经过 Harness。Schema、顺序、循环和 L3 检查对未接入的业务工具不会执行。

## 验证建议

新增 MainAgent Toolkit 集成测试：枚举最终注册工具及 middleware 链，分别触发 product_search、create_order 和 cancel_order，断言 Harness 事件/违规真实出现。
