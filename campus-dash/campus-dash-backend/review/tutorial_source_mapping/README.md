# 钉钉教程 × CampusDash 源码逐篇导航

本目录把钉钉知识库“校园跑腿后端-基础部分”与当前本地源码逐篇对齐。它不是教程摘要，而是代码阅读入口：先看一章在系统中的位置，再沿链接进入真实入口、数据变化、副作用与失败路径。

> 核验基线：2026-09-05 内置浏览器目录。钉钉当前实际有 **33 个文档**；`09 并发压测与调优篇`同时存在两份“第29章”，与 [`docs/P8-教程正文完成报告.md`](../../docs/P8-%E6%95%99%E7%A8%8B%E6%AD%A3%E6%96%87%E5%AE%8C%E6%88%90%E6%8A%A5%E5%91%8A.md#L5) 所记“32章”不一致。这里不擅自合并，按在线文档一一保留。

## 先建立整体认知

1. [`review/01_project_overview.md`](../01_project_overview.md)：进程、模块、能力接线状态。
2. [`review/02_core_call_chain.md`](../02_core_call_chain.md)：发布、抢单、超时流转、结算、缓存、消息的完整链路。
3. 再按下表逐章阅读；每个模块的当前隐患在上述文档的对应功能节内，与实际流程一起核对。

## 源码优先与本轮纠偏

教程标题只组织阅读顺序；实现结论以当前方法体、调用者、装配条件、SQL/Lua 为依据。源码注释、补充文档和测试名称也可能描述设计意图，需要与执行分支核对。链接存在且行号不越界，只能证明导航有效，不能证明描述正确。

本轮按调用链纠正了以下关键偏差：Lua 没有任务状态字段；抢单在 Lua 前已读 DB；状态更新并非全经过领域方法；超时换人直接调用仓储；首轮消息与抢单分事务；关闭 MQ 后空发送仍可能标 SENT；详情缓存命中后 Controller 仍查库；资金消费者不计信用分；托管实际转移 available；对账不覆盖全部用户余额。详见第07—23章对应章节。

当前输出提供静态源码解释和风险推导，不把测试源码存在、历史压测报告或配置数值表述为本轮运行验证。源码方法链接应落到对应方法，调用点链接应明确表示调用位置；“有定义”“有调用”“默认装配”“运行验证”分别取证。

## 逐篇索引

| 篇 | 本地逐章解读 |
|---|---|
| 00 项目与架构篇 | [01 选题与业务全景](01_business_overview.md) · [02 DDD 洋葱架构](02_ddd_onion_contexts.md) · [03 Maven 多模块](03_maven_modules.md) |
| 01 并发基础篇 | [04 JMM/JUC](04_jmm_juc.md) · [05 线程池与异步编排](05_thread_pool_async.md) · [06 JDK 21 虚拟线程](06_virtual_threads.md) |
| 02 抢单并发篇 | [07 N 抢 1 演进](07_grab_solution_evolution.md) · [08 Redis Lua](08_redis_lua_idempotency.md) · [09 DB CAS 与唯一索引](09_db_cas_unique_index.md) |
| 03 状态机与延迟流转篇 | [10 状态机与状态日志](10_state_machine.md) · [11 RocketMQ 定时消息](11_delay_queue_rocketmq.md) · [12 超时流转与候选队列](12_timeout_transfer.md) |
| 04 资金托管与一致性篇 | [13 复式记账](13_double_entry.md) · [14 Spring 事务](14_spring_transactions.md) · [15 本地消息与事务消息](15_local_message_transaction_message.md) · [16 对账与补偿](16_reconciliation.md) |
| 05 数据同步篇 | [17 缓存与 DB 一致性](17_cache_db_consistency.md) · [18 Redis 与热 Key](18_redis_hot_key.md) · [19 不做 Canal→ES](19_no_canal_es.md) · [20 穿透/击穿/雪崩](20_cache_failures.md) |
| 06 信用分与风控篇 | [21 事件驱动信用分](21_credit_events.md) · [22 资格与反作弊](22_risk_control.md) |
| 07 实时推送篇 | [23 WebSocket 多端与多节点](23_websocket.md) |
| 08 分库分表与性能篇 | [24 ShardingSphere 与 ID](24_sharding_id.md) · [25 SQL 与索引](25_sql_indexes.md) |
| 09 并发压测与调优篇 | [26 工具与加压模型](26_load_models.md) · [27 尖峰与零超卖](27_spike_zero_oversell.md) · [28 六轮调优](28_tuning_iterations.md) · [29A 容量与故障注入压测](29a_capacity_fault_load.md) · [29B 容量与故障注入](29b_capacity_fault.md) |
| 10 可观测与部署篇 | [30 指标与链路追踪](30_observability.md) · [31 Compose 与 K8s](31_deployment.md) |
| 11 微服务演进篇 | [32 微服务与 TCC/Saga](32_microservices_tcc_saga.md) |

## 一条贯穿全书的代码链

[`ErrandController.grab()`](../../dash-presentation/src/main/java/com/campusdash/presentation/ErrandController.java#L157) → [`GrabErrandUseCase.grab()`](../../dash-application/src/main/java/com/campusdash/application/usecase/GrabErrandUseCase.java#L100) → Sentinel 限流/信用资格 → [`RedisGrabSlotAdapter.tryAcquire()`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/cache/RedisGrabSlotAdapter.java#L38) → [`grab.lua`](../../dash-infrastructure/src/main/resources/lua/grab.lua#L1) → [`GrabTransactionalStep.lockAndRecord()`](../../dash-application/src/main/java/com/campusdash/application/usecase/GrabTransactionalStep.java#L34) → MySQL CAS/唯一索引 → [`TimeoutTransferUseCase.scheduleFirstTimeout()`](../../dash-application/src/main/java/com/campusdash/application/usecase/TimeoutTransferUseCase.java#L160) → 缓存失效与 WebSocket 推送。

## 状态标签口径

- **默认接入**：默认配置下位于运行主链。
- **配置门控**：有真实实现，但是否装配由配置决定；例如 MQ、缓存、WebSocket、认证模式。
- **定义/测试完成，默认未接线**：代码和测试存在，但默认运行数据源没有使用它；典型是 ShardingSphere 规则。
- **教程方案未落地**：仅是演进设计或对比材料；典型是 Micrometer/Prometheus/SkyWalking、K8s、Seata TCC/Saga、Canal/ES。

