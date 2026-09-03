# 07 AGUI事件协议与WebSocket实时推送

> [钉钉原文](https://docs.dingtalk.com/i/nodes/GZLxjv9VGqgwQMXxt6BgQD5986EDybno) · 当前结论：**能力等价/部分落地**，采用自定义事件协议而非正式 AG-UI SDK。

## 当前源码对应

| 层 | 源码 |
| --- | --- |
| 事件类型与发布订阅 | [eventbus.py](../../app/infrastructure/eventbus.py) |
| AgentScope 事件映射 | [orchestrator.py](../../app/application/agents/orchestrator.py) `_consume_reply()` |
| WebSocket 连接管理 | [connection.py](../../app/presentation/connection.py) |
| 浏览器消费 | [App.tsx](../../frontend/src/App.tsx) `ws.onmessage` |

## 真实调用链

[React 建立 WebSocket 并处理消息](../../frontend/src/App.tsx#L34) → [FastAPI 注册事件端点](../../app/presentation/server.py#L54) → [ConnectionManager 按 session 管理连接](../../app/presentation/connection.py#L21)。HTTP 则由 [submit_intent](../../app/presentation/server.py#L131) 单独提交意图；[Orchestrator 消费流式块](../../app/application/agents/orchestrator.py#L329) 和工具发布 `token.delta`、`tool.*`、`agent.dispatch`、`plan.update`、`final.result`、`error`，最后由 [EventBus.publish](../../app/infrastructure/eventbus.py#L107) 推送给对应 WebSocket。

队列模式下，worker 产生的事件先走 Redis Pub/Sub backplane，再进入 API 进程内 EventBus，最后发送给浏览器。

## 数据、副作用与失败

- `token.delta` 用于实时展示但不落对话事件表；关键非 token 事件轮末批量落库。
- WebSocket 是过程通道，HTTP 是提交和最终结果通道；任一通道断开不应混淆另一通道职责。
- 推送失败会清理连接；队列 API 还会轮询任务状态兜底等待最终结果。

## 与教程的差异

事件语义接近 AG-UI，但字段、兼容性和版本协商由本项目自己维护。对外宣称时应称“自定义 AG-UI 风格协议”，不要说已接入官方协议包。
