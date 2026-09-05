# 第24章：ShardingSphere 分片与分布式 ID × 源码

- 钉钉原文：[第24章-ShardingSphere 分片与分布式 ID](https://docs.dingtalk.com/i/nodes/ndMj49yWjXrj207OUblNPqrXJ3pmz5aA)
- 本地补充：[数据库分片相关思考](../../docs/%E6%95%B0%E6%8D%AE%E5%BA%93%E5%88%86%E7%89%87%E7%9B%B8%E5%85%B3%E6%80%9D%E8%80%83.md#L6)

## 已完成

[`CampusDashShardingRuleFactory.create()`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/sharding/CampusDashShardingRuleFactory.java#L28) 为任务绑定表按 `campus_id`、用户表按 `user_id` 生成规则；[`CampusDashModuloShardingAlgorithm.doSharding()`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/sharding/CampusDashModuloShardingAlgorithm.java#L30) 实现取模路由。迁移脚本 [`migrate-p6.sql`](../../docker/migrate-p6.sql#L1) 补齐共片字段和索引。

[`SnowflakeIdGenerator`](../../dash-shared/src/main/java/com/campusdash/shared/SnowflakeIdGenerator.java#L8) 生成跨进程 ID，在线/worker 使用不同 workerId。

## 默认未接线

默认 [`application.yaml`](../../dash-bootstrap/src/main/resources/application.yaml#L8) 仍是普通 MySQL JDBC URL，没有构造并替换为 ShardingSphere DataSource。规则、算法与测试存在，但默认运行流量未真正经过分片中间件；不能写成“线上已分四库”。

