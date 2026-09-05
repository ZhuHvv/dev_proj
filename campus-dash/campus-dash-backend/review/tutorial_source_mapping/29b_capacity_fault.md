# 第29章B：容量估算与故障注入 × 源码

- 钉钉原文：[第29章-容量估算与故障注入](https://docs.dingtalk.com/i/nodes/1DKw2zgV2Pxk3MmDtvXbAYNR8B5r9YAn)

此文档是钉钉目录中与“第29章-容量估算与故障注入压测”并存的第二份第29章。为满足一一对应，这里独立保留；内容阅读时应与 [29A](29a_capacity_fault_load.md) 对照，避免把两份文档当成两个连续章节。

## 项目降级矩阵

- MQ：[`NoopDelayMessageAdapter`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/config/NoopDelayMessageAdapter.java#L24) + worker 扫描。
- 缓存延迟双删：[`NoopCacheEvictAdapter`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/cache/NoopCacheEvictAdapter.java#L18) 仅保留首次删除与 TTL。
- WebSocket：[`NoopRealtimeNotifier`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/realtime/NoopRealtimeNotifier.java#L13)，业务结果不回滚。
- 抢单限流：可在 Sentinel 与本地固定窗口实现间切换；本地实现只保护单实例。

## 不可降级核心

MySQL 是交易事实源，Redis 是抢单原子预裁决；两者故障没有透明替代路径。容量规划应通过限流、快速失败和恢复演练保护它们，而不是在故障时临时切换到语义不同的实现。

