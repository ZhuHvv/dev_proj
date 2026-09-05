# 第01章：选题与业务全景 × 源码

- 钉钉原文：[第01章-选题与业务全景](https://docs.dingtalk.com/i/nodes/vNG4YZ7JnP9OlBYqtAzdBdaOW2LD0oRE)
- 本地补充：[架构设计与技术选型](../../docs/%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1%E4%B8%8E%E6%8A%80%E6%9C%AF%E9%80%89%E5%9E%8B.md#L35) · [设计演进记录](../../docs/%E8%AE%BE%E8%AE%A1%E6%BC%94%E8%BF%9B%E8%AE%B0%E5%BD%95.md#L30)

## 在整体链路中的位置

发单人、跑腿、平台三方围绕任务与托管资金形成业务流程：发布并把发单人可用余额转入系统托管户 → N 抢 1 → 确认/超时换人 → 取货/送达 → 人工或自动结算 → 信用、通知、对账。这里“托管”不表示用户账户 frozen 字段增加；当前 SQL 修改双方 available。

## 真实入口与调用链

浏览器请求从 [`ErrandController`](../../dash-presentation/src/main/java/com/campusdash/presentation/ErrandController.java#L29) 进入；发布走 [`PublishErrandUseCase.publish()`](../../dash-application/src/main/java/com/campusdash/application/usecase/PublishErrandUseCase.java#L67)，抢单走 [`GrabErrandUseCase.grab()`](../../dash-application/src/main/java/com/campusdash/application/usecase/GrabErrandUseCase.java#L100)，履约状态由 [`Errand`](../../dash-domain/src/main/java/com/campusdash/domain/errand/model/Errand.java#L18) 统一约束，后台超时和对账由 [`WorkerApplication`](../../dash-worker/src/main/java/com/campusdash/worker/WorkerApplication.java#L27) 承担。

## 数据变化与副作用

主数据在 [`docker/init.sql`](../../docker/init.sql#L5)：`errand` 是任务快照，`errand_status_log` 是状态轨迹，`grab_record` 记录抢单，`wallet_account`/`wallet_ledger`/`escrow_order`构成资金账，`local_message`、`notification`、`recon_diff`、`credit_event`支撑异步闭环。

## 当前边界

默认运行依赖 MySQL、Redis 和启用状态下的 RocketMQ；“零超卖”不等于整个业务无并发缺陷。结算权限、自抢、Redis 回滚和信用事件原子性等问题应同时看 [核心调用链各模块的当前隐患](../02_core_call_chain.md)。

