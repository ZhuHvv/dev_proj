# 第30章：指标看板与链路追踪 × 源码

- 钉钉原文：[第30章-指标看板与链路追踪](https://docs.dingtalk.com/i/nodes/LeBq413JAw62YKDRCzoOkZ2qWDOnGvpb)

## 当前已有的观测点

[`GetErrandDetailUseCase`](../../dash-application/src/main/java/com/campusdash/application/usecase/query/GetErrandDetailUseCase.java#L116) 暴露进程内请求/缓存命中/DB 加载计数；[`CacheEvictSupport`](../../dash-application/src/main/java/com/campusdash/application/usecase/CacheEvictSupport.java#L111) 记录失效失败数；[`InternalController`](../../dash-presentation/src/main/java/com/campusdash/presentation/InternalController.java#L36) 提供内部查看入口。压测轮次和正确性结果由 `bench_run*` 表与报告保存。

计数口径有两个限制：dbLoadCount 只计缓存用例内 reload，不含 Controller 再次查库；RedisErrandCacheAdapter.evict 自己捕获删除异常，上层 CacheEvictSupport 不一定收到异常并增加 evictFailureCount。因此这些计数既不是 HTTP 总 DB 查询量，也不是完整的缓存失效失败量。

## 教程方案未落地

根 `pom.xml` 没有 Actuator、Micrometer、Prometheus Registry、OpenTelemetry/SkyWalking 依赖，配置也没有正式 metrics/tracing 导出。因此“Prometheus + Grafana 看板”“全链路 traceId”是目标设计，不是当前运行事实。

## 下一步最小闭环

先把抢单各层结果、DB CAS 冲突、MQ 延迟/积压、缓存命中/重建/失效失败、资金差异数接到 Micrometer，再加入 HTTP→用例→JDBC/Redis/MQ 的 trace。没有统一导出前，日志和内部计数只适合单实例排障。
