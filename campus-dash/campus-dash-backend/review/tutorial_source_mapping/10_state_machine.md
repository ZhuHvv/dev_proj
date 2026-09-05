# 第10章：任务状态机与状态轨迹 × 源码

- 钉钉原文：[第10章-任务状态机设计与事件溯源](https://docs.dingtalk.com/i/nodes/mweZ92PV6M5zpX0Nsqlx6bAyWxEKBD6p)
- 本地补充：[状态机设计](../../docs/%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1%E4%B8%8E%E6%8A%80%E6%9C%AF%E9%80%89%E5%9E%8B.md#L835)

## 领域模型与运行入口要分别核对

[`ErrandStatus`](../../dash-domain/src/main/java/com/campusdash/domain/errand/model/ErrandStatus.java#L16) 定义允许边；[`Errand.transitTo()`](../../dash-domain/src/main/java/com/campusdash/domain/errand/model/Errand.java#L97) 校验内存版本和目标状态。领域对象的业务方法会调用它，但实际应用用例并非全部调用这些领域方法。

发布、确认、取货、送达可追到领域方法；抢单由 [`GrabTransactionalStep.lockAndRecord()`](../../dash-application/src/main/java/com/campusdash/application/usecase/GrabTransactionalStep.java#L34) 直接调用仓储 CAS（比较并设置），超时换人由 [`TimeoutTransferStep.transfer()`](../../dash-application/src/main/java/com/campusdash/application/usecase/TimeoutTransferStep.java#L54) 直接调用 `casTransferToNext`，普通结算也直接执行 `casSettle`。因此，领域类写了权限或状态检查，不代表运行入口一定执行了这些检查。

## 状态不只在内存变化

领域对象调用 `transitTo` 时会在内存 changes 列表中记录事件。持久化日志则由用例或 Step 显式调用 `appendStatusLog` 写入 [`errand_status_log`](../../docker/init.sql#L30)，不能推断为统一消费 changes 列表的事件持久化管道。当前提供状态轨迹；没有从事件流完整重放聚合的 Event Sourcing（事件溯源）实现。

## 并发裁决

内存 `expectedVersion` 用于尽早失败，真正并发裁决仍由数据库 `WHERE version=?` 的 CAS 完成。确认与超时竞争时，只能有一方更新成功，另一方看到冲突或旧轮次。

## 已知边界

状态合法不代表操作者权限完整；普通结算和自抢权限缺口见 [结算权限](../02_core_call_chain.md#fulfillment)与[自抢检查](../02_core_call_chain.md#grab)。

