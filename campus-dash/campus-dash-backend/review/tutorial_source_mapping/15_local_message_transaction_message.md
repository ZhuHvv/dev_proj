# 第15章：本地消息表与 RocketMQ 事务消息 × 源码

- 钉钉原文：[第15章-本地消息表与 RocketMQ 事务消息](https://docs.dingtalk.com/i/nodes/9bN7RYPWdMAEeZ20sjNOxLgDVZd1wyK0)

## 两套机制解决不同问题

延迟任务使用 [`local_message`](../../docker/init.sql#L128)，但事务关系分三种：抢中首轮由 [`TimeoutTransferStep.enqueueTimeout()`](../../dash-application/src/main/java/com/campusdash/application/usecase/TimeoutTransferStep.java#L87) 在抢单提交后另开事务登记；换人下一轮登记参加 `transfer()` 的事务；送达自动结算与送达状态同事务登记，且不立即发送。首轮的抢中事实与消息登记之间存在提交间隙。

[`LocalMessageRetryJob`](../../dash-worker/src/main/java/com/campusdash/worker/LocalMessageRetryJob.java#L37) 只读取到达 next_retry_at 的 PENDING 行；登记时 next_retry_at 取计划投递时间。失败并不意味着马上重发，扫描周期和重试时间都必须满足。

资金事件使用 RocketMQ 事务消息：[`RocketMqFundEventAdapter.publishInTransaction()`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/config/RocketMqFundEventAdapter.java#L94) 先发半消息，在本地工作成功后提交；Broker（消息代理）不确定时通过 [`checkLocalTransaction()`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/config/RocketMqFundEventAdapter.java#L140) 查本地事实。

## 消费端

[`FundEventConsumer`](../../dash-worker/src/main/java/com/campusdash/worker/FundEventConsumer.java#L60) 写站内通知，没有更新信用分。信用分由业务用例直接调用信用仓储更新。另一消费组的 [`FundEventPushConsumer`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/realtime/FundEventPushConsumer.java#L59) 推送资金通知；它位于 infrastructure，worker 的扫描范围也包含它，不能限定为只在在线进程运行。

## 不能混为一谈

RocketMQ 事务消息不能同时设置任意投递时间，所以确认超时/自动结算使用“本地消息 + 定时消息”，资金一致性使用事务消息。MQ 关闭时资金端有 Noop 适配器，意味着消息副作用被明确降级，不是自动补齐。
