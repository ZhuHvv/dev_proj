# 第02章：DDD 洋葱架构与限界上下文 × 源码

- 钉钉原文：[第02章-DDD 洋葱架构与限界上下文划分](https://docs.dingtalk.com/i/nodes/Exel2BLV5zwPpkRjhp9aZX7mJgk9rpMq)
- 本地补充：[限界上下文](../../docs/%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1%E4%B8%8E%E6%8A%80%E6%9C%AF%E9%80%89%E5%9E%8B.md#L92) · [洋葱分层](../../docs/%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1%E4%B8%8E%E6%8A%80%E6%9C%AF%E9%80%89%E5%9E%8B.md#L143)

## 从外到内

`dash-presentation` 负责 HTTP/认证/WebSocket，`dash-application` 编排事务和用例，`dash-domain` 保存任务、资金、信用模型与端口，`dash-infrastructure` 实现 JDBC（Java 数据库连接）、Redis、RocketMQ 等适配器，`dash-bootstrap` 只负责装配。

依赖倒置的实证是应用层依赖 [`ErrandRepository`](../../dash-domain/src/main/java/com/campusdash/domain/errand/ports/ErrandRepository.java#L13)、[`GrabSlotPort`](../../dash-domain/src/main/java/com/campusdash/domain/grab/ports/GrabSlotPort.java#L12)、[`FundEventPort`](../../dash-domain/src/main/java/com/campusdash/domain/wallet/ports/FundEventPort.java#L14)，而不是依赖 `Jdbc*`、`Redis*`、`RocketMq*` 类。

## 一个纵向切片

[`ErrandController.grab()`](../../dash-presentation/src/main/java/com/campusdash/presentation/ErrandController.java#L157) → [`GrabErrandUseCase`](../../dash-application/src/main/java/com/campusdash/application/usecase/GrabErrandUseCase.java#L32) → 领域端口 → [`RedisGrabSlotAdapter`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/cache/RedisGrabSlotAdapter.java#L21) / [`JdbcErrandRepository`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/persistence/JdbcErrandRepository.java#L23)。

## 需要防止的误读

这是模块化单体中的领域分层，不代表每个包都是独立微服务；进程边界目前只有在线应用和 worker。领域对象负责状态合法性，但跨聚合事务、消息发送与缓存失效仍在应用层完成。

