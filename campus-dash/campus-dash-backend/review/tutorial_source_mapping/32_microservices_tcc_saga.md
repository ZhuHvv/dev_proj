# 第32章：微服务边界与 Seata TCC/Saga × 源码

- 钉钉原文：[第32章-拆分边界与 Seata TCC Saga 对照](https://docs.dingtalk.com/i/nodes/7dx2rn0JbYBAo2X7fNGpdnaxVMGjLRb3)
- 本地补充：[微服务演进路径](../../docs/%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1%E4%B8%8E%E6%8A%80%E6%9C%AF%E9%80%89%E5%9E%8B.md#L993)

## 当前架构结论

当前是 Maven 多模块的模块化单体，在线进程内通过本地方法调用 application/domain/infrastructure；只有后台 worker 是第二进程。仓库没有注册中心、Feign/RPC、API Gateway、Seata Server 或 TCC/Saga 事务日志实现。

## 如果拆分，最先断开的事务

[`PublishErrandUseCase.publish()`](../../dash-application/src/main/java/com/campusdash/application/usecase/PublishErrandUseCase.java#L67) 当前在一个本地事务里完成钱包扣减、复式流水、托管单和任务发布。拆成任务/钱包服务后，这条原子事务消失，才需要 TCC（Try/Confirm/Cancel，尝试/确认/取消）或 Saga（长事务补偿链）。

## 可复用的现有基础

领域端口、稳定业务号、唯一索引、本地消息、事务消息和对账表能降低拆分成本，但不等于已经实现分布式事务。拆分前的触发信号应来自团队边界、独立扩缩容或技术栈差异，而不是“模块多了”。

## 推荐阅读闭环

从 [`01_project_overview.md`](../01_project_overview.md#runtime) 看两个进程，再读 [`PublishErrandUseCase`](../../dash-application/src/main/java/com/campusdash/application/usecase/PublishErrandUseCase.java#L67) 的本地事务，最后对照架构文档中的 TCC 表；这样能明确“现在拥有的简单性”和“拆分后必须补回的能力”。

