# 第09章：数据库 CAS 与唯一索引 × 源码

- 钉钉原文：[第09章-DB 乐观锁 CAS 与唯一索引兜底](https://docs.dingtalk.com/i/nodes/1DKw2zgV2Pxk3MmDtvXbAkpa8B5r9YAn)

CAS（Compare-And-Set，比较并设置）是数据库最终裁决：[`GrabTransactionalStep.lockAndRecord()`](../../dash-application/src/main/java/com/campusdash/application/usecase/GrabTransactionalStep.java#L34) 先调用 [`ErrandRepository.casLockForRunner()`](../../dash-domain/src/main/java/com/campusdash/domain/errand/ports/ErrandRepository.java#L13)，真实 SQL 在 [`JdbcErrandRepository`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/persistence/JdbcErrandRepository.java#L23)，条件同时约束状态和版本。

## 同一事务内的三步

1. `errand` 状态/版本条件更新。
2. [`JdbcGrabRecordRepository.insert()`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/persistence/JdbcGrabRecordRepository.java#L23) 写抢单记录。
3. 写 `errand_status_log`。

[`grab_record`](../../docker/init.sql#L44) 的 `uk_errand_round_seq` 和 `uk_errand_round_user` 双唯一索引是最后一道约束。插入撞唯一键会抛异常，让前面的 CAS 一并回滚。

## 与 Redis 的职责分工

Redis 是高吞吐预裁决，MySQL 是事实源；两者不是分布式事务。DB 失败后由应用补偿 Redis，因此仍需关注补偿失败、幂等状态与对账，而不能把“唯一索引存在”等同于全链无窗口。
