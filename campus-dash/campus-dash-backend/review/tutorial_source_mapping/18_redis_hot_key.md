# 第18章：Redis 缓存与热 Key 治理 × 源码

- 钉钉原文：[第18章-Redis 缓存设计与热 Key 治理](https://docs.dingtalk.com/i/nodes/DnRL6jAJMGp7P2mlh9jnE5qxWyMoPYe1)

## Key 与分片

[`RedisErrandCacheAdapter`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/cache/RedisErrandCacheAdapter.java#L39) 把同一任务详情复制为多个缓存分片：读随机选一片，写后失效删除所有片，以分散单 Key 读热点。默认分片数、TTL、抖动、空值 TTL 和双删间隔在 [`application.yaml`](../../dash-bootstrap/src/main/resources/application.yaml#L52)。

## 重建控制

[`GetErrandDetailUseCase`](../../dash-application/src/main/java/com/campusdash/application/usecase/query/GetErrandDetailUseCase.java#L63) 在逻辑过期后尝试获取重建锁；抢不到锁的请求可继续用旧值，避免大量线程同时穿透数据库。

## 边界

冷未命中没有重建锁；逻辑过期分支拿锁者同步回源，锁租期为 10 秒，超长回源仍可能重叠。HTTP 详情在缓存用例之后还查一次 DB，因此这里的缓存分片和命中率不能直接证明接口降低了多少 DB 查询，见 [真实读链](17_cache_db_consistency.md)。

热 Key 分片以更多副本和更复杂失效换吞吐；它不消除 Redis 单机/集群容量瓶颈。项目没有本地 Caffeine 二级缓存，因此不存在本地缓存与 Redis 的第三份一致性问题。
