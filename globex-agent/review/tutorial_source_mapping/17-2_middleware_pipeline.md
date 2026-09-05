# 17-2 Middleware-Hook-Pipeline与工具调用生命周期

> [钉钉原文](https://docs.dingtalk.com/i/nodes/yQod3RxJKGkMNXZ5hoZX9qkqJkb4Mw9r) · 当前结论：**使用 AgentScope Middleware 做等价实现**。

## 当前源码对应

[harness_middleware.py](../../app/infrastructure/harness_middleware.py) 与 [resilience.py](../../app/infrastructure/resilience.py) 都实现 AgentScope `ToolMiddlewareBase`；工具在各 Factory 的 `build_tools()` 中注册。

## 生命周期

对实际挂载 Harness 的工具：[on_tool_call](D:/codes/dev_proj/globex-agent/app/infrastructure/harness_middleware.py:66) → SequencingTracker.check（可拒绝执行）→ LoopDetector.check（追加收敛提示）→ sequencing.record → next_handler 执行工具 → 收集 chunks → 对最后一个 chunk 执行 check_schema → sanitize_tool_output → 重建 ToolChunk。Schema 检查发生在执行后，检查返回结构；循环检测只追加提示，不直接中止工具调用。

中间件是洋葱结构：外层先进入、后退出。注册顺序会决定 Harness 看到的是原始异常、重试后的结果还是已经转成 `[error]` 的 ToolChunk。

## 数据与副作用

当前 before 阶段执行顺序检查和循环提示；after 阶段检查结果 schema 并过滤内容。语义正确性验证尚不能视为已接入。

## 与教程的差异

本仓没有单独自建 Hook Registry/Pipeline 框架，而是复用 AgentScope 中间件。概念可以一一映射，但实际覆盖范围必须按最终 Toolkit 接线核对，参见 [17-1](17-1_harness_mapping.md)。
