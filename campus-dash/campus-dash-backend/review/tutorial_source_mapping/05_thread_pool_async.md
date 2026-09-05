# 第05章：线程池隔离与 CompletableFuture × 源码

- 钉钉原文：[第05章-线程池隔离与 CompletableFuture 编排](https://docs.dingtalk.com/i/nodes/bva6QBXJwa2OR5DgtLPAbXwrWn4qY5Pr)

## 当前实现是什么

在线主链没有用 `CompletableFuture` 把发布/抢单/结算并行化，也没有按业务自建多个 `ThreadPoolTaskExecutor`。HTTP 请求由 Tomcat 线程处理，默认上限见 [`application.yaml`](../../dash-bootstrap/src/main/resources/application.yaml#L1)；JDBC、Redis 和 RocketMQ 调用仍以同步方式编排。

后台任务由独立 `dash-worker` 进程隔离：[`TimeoutScanJob`](../../dash-worker/src/main/java/com/campusdash/worker/TimeoutScanJob.java#L43)、[`LocalMessageRetryJob`](../../dash-worker/src/main/java/com/campusdash/worker/LocalMessageRetryJob.java#L36)、[`ReconciliationJob`](../../dash-worker/src/main/java/com/campusdash/worker/ReconciliationJob.java#L36) 通过 Spring 调度运行。

## 为什么这仍是隔离

隔离单位目前是“进程 + 数据库连接池”，而不是每类业务线程池。worker 的 HikariCP（数据库连接池）上限为 10，在线进程为 20，避免后台批处理与在线请求完全共用执行资源。

## 教程与代码差异

`CompletableFuture` 是教程中的可选编排方法，不是当前主链事实。资金、状态 CAS 和本地消息需要明确事务顺序，不能为追求并行而随意拆开。

