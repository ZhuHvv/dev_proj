# 第16章：结算对账与差异补偿 × 源码

- 钉钉原文：[第16章-结算对账与差异补偿](https://docs.dingtalk.com/i/nodes/mweZ92PV6M5zpX0NsqlxzADpWxEKBD6p)

## 对账入口

[`ReconciliationJob.runDaily()`](../../dash-worker/src/main/java/com/campusdash/worker/ReconciliationJob.java#L37) 每日调用 [`JdbcReconRepository`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/persistence/JdbcReconRepository.java#L19) 比较账户快照与流水净额、托管单与任务状态，并把差异写入 [`recon_diff`](../../docker/init.sql#L211)。

实际 SQL 范围：L1 汇总全历史借贷差额；L2 只比较 ESCROW/COMMISSION 系统账户，不含 USER 余额；L3 检查特定状态和流水存在性，不核对全部金额与收款人。运行日期只标记差异记录，不是交易日期筛选条件。

## 对账与补偿的区别

当前代码主要完成“发现并持久化差异”，没有通用的自动修账引擎。人工或后续任务应根据差异类型决定重放消息、补记流水、恢复余额还是标记异常；自动补钱会放大误判风险。

## 证据边界

资金账存在业务唯一键、事务边界和对账扫描，但仓库没有数据库备份恢复编排，也没有证明所有历史差异都能自动闭环。能力范围与缺口见 [对账覆盖范围](../02_core_call_chain.md#reconciliation)。

