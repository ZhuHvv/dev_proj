# 第12章：超时流转与候选队列 × 源码

- 钉钉原文：[第12章-超时流转与候选队列](https://docs.dingtalk.com/i/nodes/bva6QBXJwa2OR5DgtLPAb7XpWn4qY5Pr)

## 候选人从哪里来

抢单名额已满或数据库冲突时，[`GrabErrandUseCase.enqueueCandidate()`](../../dash-application/src/main/java/com/campusdash/application/usecase/GrabErrandUseCase.java#L182) 按“时间戳减信用分加权”写入 [`RedisCandidateQueueAdapter`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/cache/RedisCandidateQueueAdapter.java#L1) 的有序集合。

## 真实流转链

MQ 消费或扫描 → [`TimeoutTransferUseCase.handleTimeout()`](../../dash-application/src/main/java/com/campusdash/application/usecase/TimeoutTransferUseCase.java#L96) → `candidateQueue.pollBest` → [`TimeoutTransferStep.transfer()`](../../dash-application/src/main/java/com/campusdash/application/usecase/TimeoutTransferStep.java#L54) → [`JdbcErrandRepository.casTransferToNext()`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/persistence/JdbcErrandRepository.java#L121) → 同事务写状态日志和下一轮本地消息 → Step 返回并提交 → 事务外 dispatch。

这条链没有调用 `Errand.transferToNextRunner()`。SQL 直接更新 grabber、round、version、locked_at；成功换人分支也没有同步 Redis grabbed 集合、删除详情缓存或推送状态。阅读时要把这些缺失与实际执行的动作一起记住。

候选队列为空或超过最大轮数时走 [`TimeoutTransferStep.revert()`](../../dash-application/src/main/java/com/campusdash/application/usecase/TimeoutTransferStep.java#L71)，任务回到 `PUBLISHED` 并归还名额。

## 关键并发边界

[`pollBest()`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/cache/RedisCandidateQueueAdapter.java#L30) 本身就是两步 ZRANGE、ZREM，没有原子弹出；数据库迁移又是另一个事务。CAS 返回失败时重新入队使用当前时间，原信用权重丢失；Step 抛异常时没有对应的统一回补。候选被选中时未重查资格，成功换人也未同步 Redis grabbed，后续按新跑腿归还名额可能 SREM=0 而不归还，见 [候选队列与名额归还](../02_core_call_chain.md#timeout)。

