# 第07章：N 抢 1 六种方案 × 源码

- 钉钉原文：[第07章-N 抢 1 的六种方案与演进对比](https://docs.dingtalk.com/i/nodes/y20BglGWO2z0XZ7EUvN4P0EX8A7depqY)
- 本地补充：[六种方案比较](../../docs/%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1%E4%B8%8E%E6%8A%80%E6%9C%AF%E9%80%89%E5%9E%8B.md#L296)

## 当前终选不是单一锁

[`GrabErrandUseCase.grab()`](../../dash-application/src/main/java/com/campusdash/application/usecase/GrabErrandUseCase.java#L100) 实现四层防护：Sentinel 热点限流 → 后端信用/在途任务资格 → Redis Lua 原子占位 → MySQL CAS + 唯一索引最终裁决。

## 为什么不用 JVM 锁作最终方案

`synchronized`、`ReentrantLock` 只在单 JVM 生效；跨实例裁决由共享存储承担。当前 Lua 减少后续 DB 写竞争，但在 Lua 之前已经查询信用分和在途任务数，不能据此声称失败请求不访问数据库。

## 失败链

grab 的 try/catch 同时包住 DB 操作和提交后的首轮消息登记、再次查询任务、推送调用。后续抛 RuntimeException 也会补偿 Redis，即使 DB 抢单已经提交；“进入 catch”不能等同于“DB 已回滚”。补偿失败本身没有持久化重试机制。

Lua 成功而 DB 失败时，[`GrabErrandUseCase`](../../dash-application/src/main/java/com/campusdash/application/usecase/GrabErrandUseCase.java#L137) 调用 `rollback` 补回名额。注意审计发现换人后回退和请求幂等结果仍有边界，见 [换人后的名额归还](../02_core_call_chain.md#timeout) 与 [抢单请求幂等](../02_core_call_chain.md#grab)。

