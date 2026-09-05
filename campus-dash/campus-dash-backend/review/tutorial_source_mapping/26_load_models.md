# 第26章：压测工具与加压模型 × 源码

- 钉钉原文：[第26章-压测工具选型与加压模型](https://docs.dingtalk.com/i/nodes/7QG4Yx2JpLgYn5yBtqEN26PpJ9dEq3XD)
- 本地补充：[压测三条纪律](../../docs/%E5%8E%8B%E6%B5%8B%E6%96%B9%E6%A1%88%E4%B8%8E%E5%AE%B9%E9%87%8F%E8%AF%84%E4%BC%B0.md#L12)

## 工具分工

[`SpikeLoadClient`](../../dash-bench/src/main/java/com/campusdash/bench/SpikeLoadClient.java#L28) 负责“同时开闸”的 N 抢 1 尖峰；[`RampLoadClient`](../../dash-bench/src/main/java/com/campusdash/bench/RampLoadClient.java#L28) 负责阶梯加压；[`CacheLoadClient`](../../dash-bench/src/main/java/com/campusdash/bench/CacheLoadClient.java#L29) 负责读写混合缓存场景；[`DelayMessageProbe`](../../dash-bench/src/main/java/com/campusdash/bench/DelayMessageProbe.java#L27) 测定时消息偏差。

[`BenchRunRecorder`](../../dash-bench/src/main/java/com/campusdash/bench/BenchRunRecorder.java#L46) 把轮次、环境、任务 ID 和摘要写数据库，便于改动前后对照；[`bench/scripts`](../../bench/scripts/verify_run.sql#L1) 从数据库侧验超卖、重复、状态与资金平衡。

S2 的 RampLoadClient 实际请求任务列表 GET `/api/errands?campusId=1&status=PUBLISHED&size=20`，并不是抢单接口。每个虚拟任务收到响应后再发下一次请求，属于固定并发的闭环模型，响应变慢会使实际发压速率下降。不能把它的拐点直接当作抢单写链路容量。

## 三条纪律

发压端与服务端隔离、先预热、只取稳态区间。吞吐数字如果没有环境、并发模型、错误率和 DB 正确性校验，就不能作为容量结论。
