# 第14章：Spring 事务传播与失效场景 × 源码

- 钉钉原文：[第14章-Spring 事务传播与失效场景](https://docs.dingtalk.com/i/nodes/GZLxjv9VGqgwQMXxtZK25G9e86EDybno)
- 本地补充：[事务传播与失效](../../docs/%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1%E4%B8%8E%E6%8A%80%E6%9C%AF%E9%80%89%E5%9E%8B.md#L635)

## 真实事务边界

发布直接在 [`PublishErrandUseCase.publish()`](../../dash-application/src/main/java/com/campusdash/application/usecase/PublishErrandUseCase.java#L67) 开事务。抢单把“DB CAS + 抢单记录 + 状态日志”拆到独立 Bean [`GrabTransactionalStep`](../../dash-application/src/main/java/com/campusdash/application/usecase/GrabTransactionalStep.java#L19)，避免同类自调用绕过 Spring 代理。

超时流转同样拆出 [`TimeoutTransferStep`](../../dash-application/src/main/java/com/campusdash/application/usecase/TimeoutTransferStep.java#L26)。对账审计日志用 [`JdbcFundAuditAdapter`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/persistence/JdbcFundAuditAdapter.java#L38) 的 `REQUIRES_NEW`（新事务），使外层失败时审计仍可独立提交。

## 外部副作用与实际发生时间

Redis 补偿、MQ 发送、缓存失效、WebSocket 推送不能被 JDBC 本地事务回滚。项目通过 afterCommit（提交后回调）、本地消息、事务消息、重试和扫描分层处理，而不是假设 `@Transactional` 包住一切。

“不参加 DB 事务”不等于“在提交之后执行”。发布的 initSlot/registerExisting 在代理提交之前；确认、取货、送达的同步推送也在事务方法内。缓存失效默认通过 afterCommit 延后；抢单 Step 提交后才独立登记首轮消息。

结算使用 TransactionTemplate（程序化事务）。[`SettleErrandUseCase`](../../dash-application/src/main/java/com/campusdash/application/usecase/SettleErrandUseCase.java#L87) 的 doSettle 先修改托管状态，后做任务 CAS；后者失败仅 return false，没有抛异常或标记 rollback-only，事务会正常提交此前更新。资金消息 rollback 无法撤回已提交的 DB 事务。

## 仍需警惕

代理、自调用、lambda 内调用、异常被吞、返回 false 而不抛异常都会改变回滚语义。审计中的结算问题说明“写了注解”不等于事务正确。
