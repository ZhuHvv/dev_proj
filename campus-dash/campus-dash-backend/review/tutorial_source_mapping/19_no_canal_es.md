# 第19章：为什么没有 Canal→ES × 源码

- 钉钉原文：[第19章-为什么没做 Canal→ES](https://docs.dingtalk.com/i/nodes/9E05BDRVQ2aGym04UP0zBZEjJ63zgkYA)
- 本地补充：[数据同步决策](../../docs/%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1%E4%B8%8E%E6%8A%80%E6%9C%AF%E9%80%89%E5%9E%8B.md#L793)

## 当前事实

仓库没有 Canal 客户端、Elasticsearch 依赖、索引 mapping、消费任务或搜索适配器。列表查询由 [`QueryErrandListUseCase`](../../dash-application/src/main/java/com/campusdash/application/usecase/query/QueryErrandListUseCase.java#L24) 调用 [`JdbcErrandQueryAdapter`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/persistence/JdbcErrandQueryAdapter.java#L13) 直接访问 MySQL。

## 为什么不引入

当前源码选择 MySQL 索引与游标分页承载列表读，没有实现搜索读模型。是否足够要根据真实数据规模、查询耗时和目标负载判断，不能由“没有接 ES”反推性能已经满足需求。Canal/ES 的选型讨论属于设计分析：引入后需要处理 binlog（数据库变更日志）延迟、重复/乱序、全量重建和运维成本。

## 演进触发条件

只有出现复杂全文/地理/多维搜索并经慢 SQL 证明确实超出 MySQL 能力时，才值得增加搜索读模型。届时 ES 是最终一致的派生视图，MySQL 仍应是交易事实源。
