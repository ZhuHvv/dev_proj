# 16-3 可观测性体系与LangFuse全链路Trace

> [钉钉原文](https://docs.dingtalk.com/i/nodes/vNG4YZ7JnP9OlBYqtNDdppEkW2LD0oRE) · 当前结论：**等价/部分落地**；当前使用 OpenTelemetry OTLP，不是 LangFuse 专用集成。

## 当前可观测面

[tracing.py](../../app/infrastructure/tracing.py) 初始化 OpenTelemetry 导出；`TradeEventBus` 提供业务事件；ConversationStore 保存最终对话和非 token 事件；预算、熔断、队列与评测另有结构化状态。

## 真实链路

观测配置：[setup_tracing](D:/codes/dev_proj/globex-agent/app/infrastructure/tracing.py:30) 初始化 OTLP exporter；[build_agent_middlewares](D:/codes/dev_proj/globex-agent/app/infrastructure/tracing.py:50) 给 Agent 添加 TracingMiddleware。业务事件另走 EventBus → WebSocket/对话事件存储。这是两套机制，EventBus.publish 并不调用 OTLP exporter；本次读取的 server/orchestrator 中没有证明 HTTP、队列和所有外部调用已自动形成完整父子 span。

## 数据与隐私

Trace 可能包含 query、Prompt、工具参数、订单和 buyer 信息；上报前应脱敏并控制采样。`token.delta` 不落对话事件表可以降低存储量，但也意味着数据库不能完整重放逐 token 输出。

## 失败边界

观测导出失败不应阻断交易主链；但要有 exporter 失败指标，否则“无 trace”会被误认为“无请求”。

## 与教程的差异

LangFuse 可作为 OTLP/LLM 观测的未来后端之一，当前源码未找到其 SDK、Prompt 管理或 dataset 集成。对外表述应是“OTel 全链路基础”，不是“已接 LangFuse”。
