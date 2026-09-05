# 16-5 工具熔断与请求排队优先级

> [钉钉原文](https://docs.dingtalk.com/i/nodes/PwkYGxZV3ZOp3jngU97ROvRQWAgozOKL) · 当前结论：**已落地，部分能力需配置启用**。

## 工具熔断

[resilience.py](../../app/infrastructure/resilience.py) 的工具中间件处理超时、重试与本地熔断；[shared_breaker.py](../../app/infrastructure/shared_breaker.py) 可用 Redis 共享多进程熔断状态，默认并非强制开启。

调用链：Agent ToolCall → [resilience middleware](../../app/infrastructure/resilience.py#L97) → [shared breaker](../../app/infrastructure/shared_breaker.py#L60) `allow?` → timeout/retry → tool → success/failure 记账 → `ToolChunk`。

## 请求队列

[redis_stream_queue.py](../../app/infrastructure/queue/redis_stream_queue.py) 用 Redis Stream 保存优先级消息、消费者组、pending 与死信；[server.py](../../app/presentation/server.py) 入队，[worker.py](../../app/worker.py) 消费。

调用链：[POST submit_intent](../../app/presentation/server.py#L131) → [_enqueue 幂等与优先级](../../app/presentation/server.py#L222) → priority stream → [worker 并发消费](../../app/worker.py#L33) → [Redis consume/ACK](../../app/infrastructure/queue/redis_stream_queue.py#L101) → [Orchestrator](../../app/application/agents/orchestrator.py#L140)；失败保留 pending/重投，超次数进 DLQ。

## 数据与副作用

队列状态、结果和幂等键写 Redis；订单工具仍需业务幂等保护，消息“至少一次”不能等价为业务“恰好一次”。共享 breaker 能避免多个 worker 同时冲击故障依赖。

## 异常边界

已启用队列后，不能推断 Redis 入队失败会自动切直跑。此外 Orchestrator 通常把内部异常转成 `[error]` 文本正常返回，worker 会将这样的返回标记 done；只有向 worker/consume 抛出的异常才进入相应失败分支。业务失败、任务状态 failed、重投和死信不是等价概念。
