# 第21章：事件驱动信用分 × 源码

- 钉钉原文：[第21章-事件驱动信用分](https://docs.dingtalk.com/i/nodes/DnRL6jAJMGp7P2mlh9jnPvlLWyMoPYe1)

## 事件与快照

[`CreditEventType`](../../dash-domain/src/main/java/com/campusdash/domain/credit/model/CreditEventType.java#L15) 定义结算、超时换人、取消、争议等分值规则；[`CreditEvent`](../../dash-domain/src/main/java/com/campusdash/domain/credit/model/CreditEvent.java#L6) 用稳定 `bizNo` 表示业务幂等；[`JdbcCreditRepository.applyEvent()`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/persistence/JdbcCreditRepository.java#L51) 写 `credit_event` 并更新 `credit_score`。

[`credit_event`](../../docker/init.sql#L255) 的 `uk_biz` 阻止同一业务事件重复计分。每日 [`CreditCalibrationJob.calibrate()`](../../dash-worker/src/main/java/com/campusdash/worker/CreditCalibrationJob.java#L31) 按时间窗口重新校准分数。

## 查询与榜单

[`QueryCreditUseCase`](../../dash-application/src/main/java/com/campusdash/application/usecase/query/QueryCreditUseCase.java#L13) 查个人分数/事件和 Redis 排行榜。

## 一致性边界

applyEvent 自身没有事务注解。普通结算在 TransactionTemplate 内调用它，事件与快照参加资金事务；超时回退在 Step 提交后独立调用，事件插入和快照更新可部分提交。事件已存在时重试会早退，不能自动补齐快照。每日校准重算 DB 分数，不更新 Redis 榜单，也不能补回未成功插入的事件。

CreditEventType 中定义枚举不代表每种业务路径都触发：当前超时换人分支没有扣分调用，回退分支才调用 applyEvent。资金消息消费者写通知，不负责信用计分。

信用事件、快照和 Redis 榜单不是一个跨存储原子事务；校准也没有同步重建榜单。见 [信用事件与校准](../02_core_call_chain.md#credit)。所以信用分是最终一致风控信号，不应作为资金正确性的唯一依据。

