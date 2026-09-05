# 第11章：延迟队列与 RocketMQ 定时消息 × 源码

- 钉钉原文：[第11章-延迟队列五种方案与 RocketMQ 定时消息](https://docs.dingtalk.com/i/nodes/gpG2NdyVX3YgzvKNu7Lz2y04WMwvDqPk)
- 本地补充：[延迟队列方案比较](../../docs/%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1%E4%B8%8E%E6%8A%80%E6%9C%AF%E9%80%89%E5%9E%8B.md#L467)

## 默认主通道

抢中后 [`TimeoutTransferUseCase.scheduleFirstTimeout()`](../../dash-application/src/main/java/com/campusdash/application/usecase/TimeoutTransferUseCase.java#L160) 先在事务中登记本地消息，再由 [`RocketMqDelayMessageAdapter.send()`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/config/RocketMqDelayMessageAdapter.java#L41) 使用 RocketMQ 5.x `setDeliveryTimestamp` 发送任意时间定时消息。

消息由 [`TimeoutTransferConsumer.start()`](../../dash-worker/src/main/java/com/campusdash/worker/TimeoutTransferConsumer.java#L58) 消费并调用超时用例。发送失败时记录仍保持待发送，`LocalMessageRetryJob` 定时重发。

## 双通道降级

[`TimeoutScanJob.scan()`](../../dash-worker/src/main/java/com/campusdash/worker/TimeoutScanJob.java#L44) 扫描已过期 `LOCKED` 任务，作为 MQ 丢失/关闭时的兜底。`dash.mq.enabled=false` 时会装配 Noop 适配器，因此系统退化为扫描而不是完全失效。

首轮消息登记在抢单提交之后的独立事务内；换人下一轮消息才与换人状态同事务。MQ 配置关闭时，NoopDelayMessageAdapter.send 正常返回，dispatch 仍 markSent；不能期待重启 MQ 后自动补投这些 SENT 行。

## 幂等条件

消息键唯一约束限制重复登记；handleTimeout 检查 DB 状态和消息 round，再用刚读到的 DB version 做 SQL 条件更新。它没有比较消息 version，也没有在用例内验证 locked_at 已到期。扫描入口有时间条件，MQ 入口依赖投递时间，见 [超时消费判定条件](../02_core_call_chain.md#timeout)。

