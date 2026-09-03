# 16-3 可观测性体系与LangFuse全链路Trace

> [钉钉原文](https://docs.dingtalk.com/i/nodes/vNG4YZ7JnP9OlBYqtNDdppEkW2LD0oRE) · 当前结论：**等价/部分落地**；当前使用 OpenTelemetry OTLP，不是 LangFuse 专用集成。

## 当前可观测面

[tracing.py](../../app/infrastructure/tracing.py) 初始化 OpenTelemetry 导出；`TradeEventBus` 提供业务事件；ConversationStore 保存最终对话和非 token 事件；预算、熔断、队列与评测另有结构化状态。

## 真实链路

[FastAPI 请求入口](../../app/presentation/server.py#L131) / [worker 入口](../../app/worker.py#L33) → [Orchestrator 请求上下文](../../app/application/agents/orchestrator.py#L140) → [LLM 上游调用](../../app/infrastructure/llm.py#L94) / 工具外部调用 → [业务事件发布](../../app/infrastructure/eventbus.py#L107) → [Agent middleware 的 OTLP 配置](../../app/infrastructure/tracing.py#L50)。同时，`tool.started/completed`、派发、压缩、最终结果等事件可按 session 重建用户可见轨迹。

## 数据与隐私

Trace 可能包含 query、Prompt、工具参数、订单和 buyer 信息；上报前应脱敏并控制采样。`token.delta` 不落对话事件表可以降低存储量，但也意味着数据库不能完整重放逐 token 输出。

## 失败边界

观测导出失败不应阻断交易主链；但要有 exporter 失败指标，否则“无 trace”会被误认为“无请求”。

## 与教程的差异

LangFuse 可作为 OTLP/LLM 观测的未来后端之一，当前源码未找到其 SDK、Prompt 管理或 dataset 集成。对外表述应是“OTel 全链路基础”，不是“已接 LangFuse”。
