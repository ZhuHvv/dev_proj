# 第13章：复式记账与账户模型 × 源码

- 钉钉原文：[第13章-复式记账与账户模型](https://docs.dingtalk.com/i/nodes/dxXB52LJqnM0N5xEUZ6gb2B58qjMp697)
- 本地补充：[资金模型](../../docs/%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1%E4%B8%8E%E6%8A%80%E6%9C%AF%E9%80%89%E5%9E%8B.md#L549)

## 模型

[`WalletAccount`](../../dash-domain/src/main/java/com/campusdash/domain/wallet/model/WalletAccount.java#L25) 保存可用/冻结余额与版本；[`LedgerEntry`](../../dash-domain/src/main/java/com/campusdash/domain/wallet/model/LedgerEntry.java#L12) 表达借贷方向与业务号；[`EscrowOrder`](../../dash-domain/src/main/java/com/campusdash/domain/wallet/model/EscrowOrder.java#L15) 表达托管状态。

## 发布到结算

[`PublishErrandUseCase.publish()`](../../dash-application/src/main/java/com/campusdash/application/usecase/PublishErrandUseCase.java#L67) 在本地事务内扣发单人可用余额、增加托管余额、写双方流水、创建 `HELD` 托管单，再把任务发布。结算由 [`SettleErrandUseCase.settle()`](../../dash-application/src/main/java/com/campusdash/application/usecase/SettleErrandUseCase.java#L87) 释放托管并按跑腿收入/平台佣金分账；退款走 [`RefundErrandUseCase`](../../dash-application/src/main/java/com/campusdash/application/usecase/RefundErrandUseCase.java#L29)。

## 数据约束

[`wallet_ledger`](../../docker/init.sql#L79) 的 `uk_biz_direction` 完整列为 `(biz_no, account_id, direction)`，按同业务、同账户、同方向去重。同一结算允许分别向跑腿和佣金账户记贷方流水。[`escrow_order`](../../docker/init.sql#L97) 用 `uk_errand` 保证一个任务一张托管单。

字段含有 frozen 不代表发布时增加它：发布调用 casDebit 扣发单人 available，再 casCredit 增加系统托管户 available。业务上称托管或冻结，实际账务是跨账户转移。

## 当前风险

审计发现部分结算失败路径可能已更新托管状态却返回失败，以及仲裁事件金额与实际分账不一致，见 [结算事务边界](../02_core_call_chain.md#fulfillment) 与 [仲裁分账与事件金额](../02_core_call_chain.md#refund)。

