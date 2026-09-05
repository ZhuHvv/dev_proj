# 第27章：抢单尖峰与零超卖验证 × 源码

- 钉钉原文：[第27章-抢单尖峰压测与零超卖验证](https://docs.dingtalk.com/i/nodes/P0MALyR8klKwN5RPUDbXBz5QW3bzYmDO)

## 如何制造真正尖峰

[`SpikeLoadClient`](../../dash-bench/src/main/java/com/campusdash/bench/SpikeLoadClient.java#L69) 为每个请求创建虚拟线程，先用 `ready` 门闩确认全部就绪，再由 `fire` 一次释放；这比循环逐个发请求更容易暴露竞态。

## 正确性证据

[`GrabConcurrencyIT`](../../dash-bootstrap/src/test/java/com/campusdash/it/GrabConcurrencyIT.java#L80) 统计成功、名额满和冲突；[`OversellControlExperimentIT`](../../dash-bootstrap/src/test/java/com/campusdash/it/OversellControlExperimentIT.java#L111) 对比非原子 Redis 与 DB 兜底。最终还要运行 [`verify_run.sql`](../../bench/scripts/verify_run.sql#L1) 检查 DB 中成功记录数、重复用户和任务状态。

## “零超卖”的准确含义

它证明特定压测轮次中 DB 最终状态没有超过名额，不自动证明请求幂等返回、Redis 补偿、候选队列、信用事件、WebSocket 推送都无缺陷。指标必须与 [核心调用链各模块的当前隐患](../02_core_call_chain.md) 的一致性窗口一起解释。

