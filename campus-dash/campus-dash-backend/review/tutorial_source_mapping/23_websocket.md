# 第23章：WebSocket 多端同步与多节点广播 × 源码

- 钉钉原文：[第23章-WebSocket 多端同步与多节点广播](https://docs.dingtalk.com/i/nodes/pYLaezmVNe26kznBHKrnQAPBWrMqPxX6)

## 单节点真实链路

[`WebSocketConfig.registerWebSocketHandlers()`](../../dash-presentation/src/main/java/com/campusdash/presentation/realtime/WebSocketConfig.java#L27) 注册 `/ws`；[`WsAuthHandshakeInterceptor`](../../dash-presentation/src/main/java/com/campusdash/presentation/realtime/WsAuthHandshakeInterceptor.java#L24) 解析 token；[`WsHandler`](../../dash-presentation/src/main/java/com/campusdash/presentation/realtime/WsHandler.java#L31) 把一个用户的多个连接放入 [`WsSessionRegistry`](../../dash-presentation/src/main/java/com/campusdash/presentation/realtime/WsSessionRegistry.java#L19)。

业务用例通过 [`RealtimeNotifier`](../../dash-domain/src/main/java/com/campusdash/domain/notify/ports/RealtimeNotifier.java#L14) 调用 [`RealtimePushService`](../../dash-presentation/src/main/java/com/campusdash/presentation/realtime/RealtimePushService.java#L26)，向该用户在本实例的所有 session 发送。

## 跨进程/跨节点

[`WorkerApplication`](../../dash-worker/src/main/java/com/campusdash/worker/WorkerApplication.java#L20) 扫描 infrastructure，而 FundEventPushConsumer 仅以 dash.mq.enabled 为装配条件。worker 也可能进入同一推送消费组，但它没有在线 WebSocket 连接。应分别核对进程扫描范围、消费组和 notifier 实现，不能把类名中的 Push 理解成只在在线实例装配。

worker 不持有连接；资金事件由在线实例的 [`FundEventPushConsumer`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/realtime/FundEventPushConsumer.java#L59) 消费再推送。多实例时，消费者组语义可能只让一个实例收到事件，而连接可能在另一个实例；粘性路由不能解决事件路由问题，见 [实时推送路由](../02_core_call_chain.md#realtime)。前端轮询是当前降级兜底。

