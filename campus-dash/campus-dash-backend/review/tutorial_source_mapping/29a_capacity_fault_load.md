# 第29章A：容量估算与故障注入压测 × 源码

- 钉钉原文：[第29章-容量估算与故障注入压测](https://docs.dingtalk.com/i/nodes/P0MALyR8klKwN5RPUDbXBjb5W3bzYmDO)
- 本地补充：[容量评估](../../docs/%E5%8E%8B%E6%B5%8B%E6%96%B9%E6%A1%88%E4%B8%8E%E5%AE%B9%E9%87%8F%E8%AF%84%E4%BC%B0.md#L236) · [S6 故障注入](../../docs/%E5%8E%8B%E6%B5%8B%E6%96%B9%E6%A1%88%E4%B8%8E%E5%AE%B9%E9%87%8F%E8%AF%84%E4%BC%B0.md#L219)

## 容量约束链

Tomcat 最大线程 200、accept queue 500；在线 HikariCP 20；Redis Lettuce 最大活跃连接 64，配置见 [`application.yaml`](../../dash-bootstrap/src/main/resources/application.yaml#L1)。容量估算必须同时考虑请求等待时间、DB/Redis 服务时间和线程/连接排队，不能只看 CPU。

## 可注入故障与预期

配置 `dash.mq.enabled=false` 时，空适配器 send 正常返回，调用方仍会 markSent，不能期待重新启用 MQ 后自动补投这些 SENT 行。定时业务靠 worker 的状态/时间扫描再次触发。MQ 已启用但实际发送抛异常时，才走 PENDING 重试路径，见 [本地消息实际周期](../02_core_call_chain.md#messages)。

配置关闭缓存时详情回源 DB；关闭 WebSocket 时缺少实时推送。Redis 抢单占位操作失败没有自动改用 DB 锁的分支；MySQL 写失败则按具体事务和异常返回处理。配置关闭与运行中故障是不同实验，必须分别验证。

## 验证重点

故障注入除了错误率，还要验 DB 是否超卖、资金是否平衡、消息是否积压后恢复、缓存是否最终收敛。恢复性比瞬时 QPS 更重要。
