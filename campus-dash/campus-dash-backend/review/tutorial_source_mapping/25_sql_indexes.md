# 第25章：慢 SQL 与索引优化 × 源码

- 钉钉原文：[第25章-慢 SQL 与索引优化](https://docs.dingtalk.com/i/nodes/DnRL6jAJMGp7P2mlh9jnyzPKWyMoPYe1)

## 查询入口

任务列表和游标分页在 [`JdbcErrandQueryAdapter`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/persistence/JdbcErrandQueryAdapter.java#L13)，单任务 CAS/扫描在 [`JdbcErrandRepository`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/persistence/JdbcErrandRepository.java#L23)，资金查询在 [`JdbcWalletQueryAdapter`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/persistence/JdbcWalletQueryAdapter.java#L11)。

## 索引与约束

真实 DDL 从 [`docker/init.sql`](../../docker/init.sql#L5) 阅读：任务需要校区/状态/创建时间组合索引；抢单记录有“轮次+序号”和“轮次+用户”唯一键；流水、托管、消息、通知、对账、信用事件都有业务幂等索引。

## 游标分页

[`QueryErrandListUseCase.listByCursor()`](../../dash-application/src/main/java/com/campusdash/application/usecase/query/QueryErrandListUseCase.java#L41) 避免深分页 OFFSET 扫描，但必须保持排序字段和游标编码一致。

## 验证边界

仓库有压测与 SQL 校验脚本，但没有当前机器上实时慢日志/`EXPLAIN ANALYZE` 结果。索引设计是源码事实，实际是否命中仍需在目标数据规模和数据库版本上验证。

