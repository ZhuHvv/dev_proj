# 第22章：抢单资格与反作弊 × 源码

- 钉钉原文：[第22章-抢单资格与反作弊](https://docs.dingtalk.com/i/nodes/y20BglGWO2z0XZ7EUvN49NPE8A7depqY)

## 服务端资格链

[`GrabErrandUseCase.grab()`](../../dash-application/src/main/java/com/campusdash/application/usecase/GrabErrandUseCase.java#L100) 先按 `errandId`/`runnerId` 进入 [`GrabRateLimiterPort`](../../dash-domain/src/main/java/com/campusdash/domain/grab/ports/GrabRateLimiterPort.java#L9)，默认实现是 [`SentinelGrabRateLimiterAdapter`](../../dash-infrastructure/src/main/java/com/campusdash/infrastructure/grab/SentinelGrabRateLimiterAdapter.java#L42)。通过后再从后端读取信用分和在途任务数，客户端传入的 `creditScore` 被明确忽略。

## 幂等与身份

HTTP 入口 [`ErrandController.grab()`](../../dash-presentation/src/main/java/com/campusdash/presentation/ErrandController.java#L157) 从认证上下文取用户，`requestId` 进入 Redis Lua 幂等判定。认证由 [`AuthInterceptor`](../../dash-presentation/src/main/java/com/campusdash/presentation/auth/AuthInterceptor.java#L36) 执行，默认不信任 `X-User-Id` 后门。

## 当前不足

没有设备指纹、IP 风险画像、行为模型或持久化限流计数。Sentinel/本地限流主要保护热点，不等于完整反作弊；审计还指出“自抢自己的任务”缺少业务校验，见 [结算权限](../02_core_call_chain.md#fulfillment)与[自抢检查](../02_core_call_chain.md#grab)。

