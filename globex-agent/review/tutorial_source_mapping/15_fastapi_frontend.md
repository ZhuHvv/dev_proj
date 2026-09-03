# 15 FastAPI接口与前后端闭环

> [钉钉原文](https://docs.dingtalk.com/i/nodes/P0MALyR8klKwN5RPUYPr52zQW3bzYmDO) · 当前结论：**已落地**。

## 两条前后端通道

[App.tsx](../../frontend/src/App.tsx) 通过 HTTP 提交意图，同时建立 WebSocket 接收过程事件；[server.py](../../app/presentation/server.py) 创建 FastAPI、处理 `/commerce/intents` 与 `/commerce/events`；[connection.py](../../app/presentation/connection.py) 管理 session 连接。

## 真实调用链

直跑：[React 提交操作](../../frontend/src/App.tsx#L79) → [submit_intent](../../app/presentation/server.py#L131) → [orchestrator.handle_intent](../../app/application/agents/orchestrator.py#L140) → `final_text` HTTP response。

队列：[React POST](../../frontend/src/App.tsx#L79) → [_enqueue](../../app/presentation/server.py#L222) → [Redis Stream consume](../../app/infrastructure/queue/redis_stream_queue.py#L101) → [worker.main](../../app/worker.py#L33) → [orchestrator](../../app/application/agents/orchestrator.py#L140) → `final.result/backplane` → [_await_result](../../app/presentation/server.py#L258) → HTTP response。

过程流：[Orchestrator/Tool 消费与映射事件](../../app/application/agents/orchestrator.py#L329) → [TradeEventBus.publish](../../app/infrastructure/eventbus.py#L107) → [ConnectionManager](../../app/presentation/connection.py#L21) → WebSocket → [ws.onmessage](../../frontend/src/App.tsx#L57) → React 更新 token、工具、计划和结果状态。

## 数据与副作用

HTTP 请求创建本轮 `ShoppingContext`；队列模式保存任务状态和幂等键；WebSocket 只按 `shopping_session_id` 订阅事件。订单和偏好写入发生在工具/UseCase，而不是路由函数本身。

## 异常路径

队列等待同时使用事件和状态轮询，避免丢事件后无限等待；WebSocket 断开会清理连接；顶层错误发布 `error` 事件并返回可解释失败。端到端验证入口是 [smoke_e2e.py](../../scripts/smoke_e2e.py)。
