# 第04章：JMM 与 JUC × 源码

- 钉钉原文：[第04章-JMM 与 JUC：从 volatile 到 AQS](https://docs.dingtalk.com/i/nodes/GZLxjv9VGqgwQMXxtZK25kOd86EDybno)

JMM（Java Memory Model，Java 内存模型）和 JUC（`java.util.concurrent` 并发工具包）在本项目不是抽象知识点，主要落在进程内统计、会话表和压测协调；跨实例正确性不能由它们单独保证。

## 代码落点

- [`WsSessionRegistry`](../../dash-presentation/src/main/java/com/campusdash/presentation/realtime/WsSessionRegistry.java#L19) 用 `ConcurrentHashMap` 保存本进程连接。
- [`RealtimePushService`](../../dash-presentation/src/main/java/com/campusdash/presentation/realtime/RealtimePushService.java#L65) 遍历连接，并在发送时对 session 做 `synchronized`，因为 `sendMessage` 非线程安全。
- [`GetErrandDetailUseCase`](../../dash-application/src/main/java/com/campusdash/application/usecase/query/GetErrandDetailUseCase.java#L37) 和 [`CacheEvictSupport`](../../dash-application/src/main/java/com/campusdash/application/usecase/CacheEvictSupport.java#L45) 用 `AtomicLong` 记录进程内指标。
- [`SnowflakeIdGenerator.nextId()`](../../dash-shared/src/main/java/com/campusdash/shared/SnowflakeIdGenerator.java#L30) 用 `synchronized` 串行化同一生成器的时间戳/序列更新。

## 边界

这些结构只保证同一 JVM（Java 虚拟机）内的可见性和原子性。抢单最终正确性依赖 Redis Lua 与数据库 CAS；WebSocket 多节点也不能靠本地 `ConcurrentHashMap` 自动广播。

