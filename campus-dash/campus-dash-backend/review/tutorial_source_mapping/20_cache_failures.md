# 第20章：缓存穿透、击穿、雪崩 × 源码

- 钉钉原文：[第20章-缓存穿透、击穿、雪崩](https://docs.dingtalk.com/i/nodes/MyQA2dXW7eqzZpbkH14mymGjJzlwrZgb)

## 三类问题的项目落点

- 穿透：[`RedisErrandCacheAdapter`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/cache/RedisErrandCacheAdapter.java#L39) 支持空值缓存；布隆过滤器由 [`BloomRebuildUseCase`](../../dash-application/src/main/java/com/campusdash/application/usecase/query/BloomRebuildUseCase.java#L33) 和 [`BloomRebuildJob`](../../dash-worker/src/main/java/com/campusdash/worker/BloomRebuildJob.java#L34) 重建。
- 击穿：详情逻辑过期 + 重建锁，见 [`GetErrandDetailUseCase`](../../dash-application/src/main/java/com/campusdash/application/usecase/query/GetErrandDetailUseCase.java#L47)。
- 雪崩：物理 TTL 加随机抖动，配置见 [`application.yaml`](../../dash-bootstrap/src/main/resources/application.yaml#L52)。

## 不应夸大的地方

发布方法已经调用 registerExisting 登记新任务，不能把缺口写成“没有登记”。实际风险是适配器吞掉登记异常、布隆已有但尚不完整时返回 false，详情会误判不存在。布隆重建逐条追加到同一个过滤器，没有全量完成后的原子切换或就绪标记。

重建锁只覆盖已有缓存的逻辑过期分支；完全未命中直接回源。关闭缓存后用例回源，Controller 对非空结果仍再次查库，不能把缓存用例的回源数当作接口总查询数。

布隆过滤器理论上允许假阳性；而“不会误杀真实任务”还依赖新增任务同步加入布隆与重建期间的双缓冲/切换语义。当前审计指出这个前提需要补全，见 [布隆登记与缓存边界](../02_core_call_chain.md#query)。

缓存整体可以通过 `dash.cache.enabled` 门控；关闭后详情回源 DB，功能可用但容量模型发生变化。

