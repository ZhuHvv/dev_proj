# 第08章：Redis Lua 原子抢单与幂等 × 源码

- 钉钉原文：[第08章-Redis Lua 原子抢单与幂等去重](https://docs.dingtalk.com/i/nodes/1DKw2zgV2Pxk3MmDtvXbGyYR8B5r9YAn)

## 真实调用链

[`GrabErrandUseCase.grab()`](../../dash-application/src/main/java/com/campusdash/application/usecase/GrabErrandUseCase.java#L100) → [`RedisGrabSlotAdapter.tryAcquire()`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/cache/RedisGrabSlotAdapter.java#L38) → [`grab.lua`](../../dash-infrastructure/src/main/resources/lua/grab.lua#L1) → `SlotOutcome`。

Lua 实际依次读取幂等键、检查名额键是否存在、检查用户集合成员、检查剩余名额，成功后执行 DECR、SADD 和 SETEX。脚本没有读取任务状态字段；名额键存在并不证明 DB 状态为 PUBLISHED。任务状态最终由数据库 SQL 约束。逆向补偿走 [`rollback_slot.lua`](../../dash-infrastructure/src/main/resources/lua/rollback_slot.lua#L1)，只有 SREM 真正删除该用户时才 INCR 名额并删幂等键。

## 数据与返回

本脚本使用名额字符串、抢中用户集合和请求幂等键三类数据。Lua 返回码由 [`SlotOutcome.fromCode()`](../../dash-domain/src/main/java/com/campusdash/domain/grab/model/SlotOutcome.java#L30) 翻译。幂等值 1 重放返回 DUPLICATE_REQUEST，应用直接报告成功；值 0 重放返回 SLOT_FULL。值 1 写入早于 DB 提交，因此不是持久化的最终成功结果。幂等键也未绑定用户归属，见 [抢单请求幂等](../02_core_call_chain.md#grab)。

## 降级边界

Redis 是抢单核心依赖，没有“Redis 挂了自动退化到数据库锁”的默认链路；这样可以避免故障时突然把洪峰全部压到 MySQL。

