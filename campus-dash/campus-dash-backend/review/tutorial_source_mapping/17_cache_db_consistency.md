# 第17章：缓存与 DB 一致性 × 源码

- 钉钉原文：[第17章-缓存与 DB 一致性](https://docs.dingtalk.com/i/nodes/1zknDm0WRamL2nbvtzOpK6KQ8BQEx5rG)
- 本地补充：[Cache Aside 三层加固](../../docs/%E7%BC%93%E5%AD%98%E4%B8%80%E8%87%B4%E6%80%A7%20Cache%20Aside%20%E4%B8%89%E5%B1%82%E5%8A%A0%E5%9B%BA.md#L4)

## 读链路

[`GetErrandDetailUseCase.detailJson()`](../../dash-application/src/main/java/com/campusdash/application/usecase/query/GetErrandDetailUseCase.java#L47) 实现 Cache Aside（旁路缓存）：先查缓存，未命中查 DB，再回填；逻辑过期时可返回旧值并竞争重建锁。

必须继续追到 [`ErrandController.detail()`](../../dash-presentation/src/main/java/com/campusdash/presentation/ErrandController.java#L129)：它只用 cachedJson 判空，随后再次 findById 组装卡片和用户动作。正常命中仍查 DB 一次；冷未命中且找到任务时查两次。缓存 JSON 没直接作为 HTTP 响应体，dbLoadCount 也不统计 Controller 的第二次查询。

重建锁只保护“已有值但逻辑过期”分支；完全未命中且布隆放行时直接 reload，没有这把锁。拿到锁者同步回源，其他请求返回旧值，并非统一后台异步重建。

## 写链路

业务事务提交后调用 [`CacheEvictSupport.evictAfterCommit()`](../../dash-application/src/main/java/com/campusdash/application/usecase/CacheEvictSupport.java#L66) 删除全部热 Key 分片，再通过 RocketMQ 安排第二次延迟删除；TTL（生存时间）是最终自愈上限。

[`CacheConsistencyCheckUseCase.runOnce()`](../../dash-application/src/main/java/com/campusdash/application/usecase/query/CacheConsistencyCheckUseCase.java#L59) 采样比较缓存/DB 并记录 `sync_diff`，它是校验兜底，不是主写路径。

## 失败语义

MQ 关闭时不投递第二次删除，仍尝试首次删除并依赖 TTL 过期。提交后删除失败不回滚数据库。TTL 只限制缓存项寿命，不是从 DB 提交起算的严格收敛期限：慢请求可能较晚回填旧值，缺失的布隆登记也不会由详情 TTL 补齐。
