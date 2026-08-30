# LibreDesk 源码审查与互联网后端场景深挖

本文是八天学习主线的横向复盘，不是新的阅读日程。目标是把“我看懂了代码”提升为“我能判断业务语义、故障边界、容量上限和改造代价”。

AI/Agent 的功能、调用链和局部风险先读 [Day 7：AI、RAG、Copilot 与自主 Agent 深入](07-ai-agent-deep-dive.md)；本文只把它放回全系统的可靠性、安全、容量和多实例语境。

下文首次使用时，P0/P1/P2 表示由高到低的处理优先级；CSRF 是跨站请求伪造，PII 是个人可识别信息，SLA 是服务等级协议，AI 是人工智能，Webhook 是事件回调。

> 基线：本地提交 `3dccdb4b`，2026-08-30 复核。
>
> 结论约定：`事实`表示当前源码直接成立；`风险`表示存在故障窗口，但没有线上数据证明已经造成事故；`方案`表示尚未实现的候选改造。

## 1. 审查结论摘要

| 优先级 | 结论 | 类型 | 主要证据 | 可能的业务影响 |
|---|---|---|---|---|
| P0 | CSRF 校验失败会把 cookie/header token 写入日志 | 事实 | `cmd/middlewares.go:authenticateUser` | Token 经日志平台、工单或截图扩散 |
| P0 | Webhook 与 AI debug 日志会记录业务正文、prompt、工具参数/结果 | 事实 | `internal/webhook/webhook.go:deliverSingleWebhook`、`internal/ai/agent.go:RunAgentWithTools` | 联系人 PII、消息内容或工具数据泄漏 |
| P1 | outgoing pending（待发送的出站消息）查询无 `LIMIT/ORDER BY/claim`（限制条数/排序/任务领取），并向有界 channel（进程内通道）阻塞发送 | 事实 | `internal/conversation/queries.sql:get-outgoing-pending-messages`、`message.go:Run` | 积压时大查询、内存增长、延迟抖动、关闭困难 |
| P1 | 多实例可能重复领取同一 pending 消息 | 风险 | 去重仅为进程内 `sync.Map` | 重复邮件或重复外部动作 |
| P1 | 外部发送与 `sent` 状态更新之间存在崩溃窗口，且状态更新错误被忽略 | 事实/风险 | `message.go:sendOutgoingMessage` | 已发送消息保持 pending，重启或下轮扫描后重复发送 |
| P1 | incoming `source_id` 只有普通索引，应用层“先查再插”不能抵御并发 | 事实/风险 | `schema.sql`、`messageExistsBySourceID` | 同一邮件重复入库、Automation/SLA 重复触发 |
| P1 | SLA 通知是“读未处理 → 发送 → 标记”，没有多实例 claim | 事实/风险 | `get-scheduled-sla-notifications`、`SendNotifications` | 多实例或崩溃窗口导致重复提醒 |
| P1 | SLA 调度调用无返回值的 Dispatcher 后就标记 processed；邮件只进入内存队列，入队或发送失败不会阻止 processed | 事实 | `internal/sla/sla.go`、`internal/notification/dispatcher.go` | 邮件提醒可能丢失且数据库不再重试；站内通知与邮件状态可能不一致 |
| P1 | 多个内存队列在满载或进程退出时允许丢任务 | 事实 | Automation、Webhook、Notification、AI Agent | 自动化、Webhook、通知或 AI 响应静默缺失 |
| P1 | Disabled AI Assistant 仍可能出现在 Assignee 列表，Worker 又会静默跳过 | 事实 | `get-agents-compact`、`internal/aiagent/worker.go:handle` | 会话留在不会回复的 AI 名下 |
| P1 | shutdown（服务关闭）不保证排空，部分生产者未纳入 WaitGroup（协程等待组），存在关闭竞态 | 风险 | `Conversation.Run/Close`、Automation `Run/Close` | SIGTERM 时丢任务、死锁或 channel panic |
| P1 | 两个核心列表查询在检查 `BeginTxx` 错误前就 `defer tx.Rollback()` | 事实 | `message.go:GetConversationMessages`、`conversation.go:GetConversations` | DB 不可达或连接池耗尽时，原本可返回的 500 可能升级成 nil Transaction panic |
| P1 | Webhook 响应体用 `io.ReadAll`，未设置大小上限 | 事实 | `deliverSingleWebhook` | 恶意或异常端点造成内存压力 |
| P1 | SSRF（服务端请求伪造）代码已接入，但样例配置默认关闭 | 事实 | `config.sample.toml [ssrf]` | 托管/多租户场景下可访问内网或元数据地址 |
| P2 | DB settings 最后加载并覆盖文件/环境变量 | 事实 | `cmd/main.go`、`cmd/init.go:loadSettings` | 配置来源不透明、不可变部署假设失效 |
| P2 | 当前仓库未集成 Prometheus/OpenTelemetry（指标监控系统/可观测性标准）等运行指标与链路追踪 | 事实 | 仅发现业务报表和可选 pprof | 队列积压、丢弃、外部调用慢等问题难以及时发现 |
| P2 | pprof 是独立、无应用认证的 HTTP Server | 事实 | `cmd/pprof.go` | 若误绑定公网会暴露运行时与性能信息 |

P0/P1 不等于已经发生生产事故，而表示从安全性、数据正确性或恢复能力看，验证与改造应优先于一般性能微调。

## 2. 消息链路的精确交付语义

### 2.1 Outgoing 的状态与故障窗口

当前状态只有 `pending/sent/failed`（待处理/已发送/失败），没有 `processing`（处理中）、attempt（尝试次数）、lease（任务租约）或 provider receipt（渠道接收回执）。

```text
HTTP QueueReply
  -> InsertMessage + LinkMessageMediaTx commit
  -> commit 后更新 participant/Conversation 快照并广播/Webhook
  -> scanner 查询全部 pending
  -> 进程内 sync.Map 去重
  -> channel
  -> Inbox.Send
  -> UpdateMessageStatus(sent 或 failed)
  -> 回复时间、SLA、广播、Automation
```

逐个故障窗口分析：

1. DB commit 前失败：Message 和附件关联一起回滚，HTTP 返回失败。
2. commit 后、快照更新前失败：Message 已存在，但列表快照可能旧；HTTP 仍可能拿到成功。
3. pending 写入后、发送前崩溃：重启可以重新扫描，属于可恢复窗口。
4. `Inbox.Send` 成功后、状态更新前崩溃：Message 仍 pending，可能重复发送。
5. `Inbox.Send` 失败，写 failed 也失败：仍可能保持 pending，下一轮自动再发，而不是只等人工 Retry。
6. 写 sent 成功后，回复时间/SLA/Automation 失败：外部消息已发，派生状态和旁路事件可能缺失。
7. Live Chat 返回 `ErrClientNotConnected`：仍标记 sent，因为 PostgreSQL 是事实来源，访客重连可拉历史，Continuity Email 还可能补发。

面试时不能说“数据库队列保证 exactly-once（恰好一次交付）”。更准确的表述是：它保证 pending 的可重新发现，但外部副作用与本地状态之间仍是至少一次/可能重复；不同渠道的幂等能力决定最终策略。

### 2.2 推荐的消息 claim 状态机

候选方案：

```text
pending
  -> processing(owner, lease_until, attempt)
  -> sent(provider_message_id, accepted_at)
  -> retry_wait(next_retry_at, last_error)
  -> failed/dead
```

claim（任务领取）应在短事务内使用 `FOR UPDATE SKIP LOCKED`（加行锁并跳过已锁行）或原子 `UPDATE ... RETURNING`（更新并返回所领取行），一次只领取有界批次。外部发送不能持有行锁；租约过期允许接管崩溃任务。仍需用稳定 Message-ID、渠道幂等键或业务去重处理“外部成功、本地确认失败”的窗口。

验证至少包括：

- 两个 Manager 同时 claim，不重复领取。
- Worker 在发送前、发送后、写状态前分别崩溃。
- lease 未过期不重领，过期后能恢复。
- 失败退避有上限和 jitter（随机抖动），避免下游恢复时惊群。
- pending 总量远大于 channel 容量时，DB 查询和内存仍有界。

### 2.3 Incoming 的幂等与附件一致性

Email 先按 `source_id` 查询，再解析 Contact/Conversation、上传附件、插入 Message、执行 hooks。当前 `source_id` 没有唯一约束，所以两个并发接收者仍可能都通过检查。

设计唯一约束前要先回答：

- Message-ID 是否只在同一 Inbox 内唯一，还是系统全局唯一？
- 空字符串与 NULL 是否参与唯一性？
- 历史数据里是否已有重复值？保留哪一条？
- 重复消息如果附件不同，是忽略、合并还是记录冲突？
- 数据库拒绝重复后，已上传但未关联的对象如何清理？

通用方案是规范化 source key，并对 `(inbox_id, normalized_source_id)` 建条件唯一索引；插入时捕获唯一冲突并按幂等成功处理。具体键仍要由 Email/Live Chat 的业务协议决定，不能直接复制伪 SQL。

## 3. 事务、最终一致性与 Outbox（事务发件箱）

`InsertMessage` 的事务只覆盖 Message 和 media 关联。participant、Conversation 快照、WebSocket、Webhook 等都在 commit 后执行，这避免长事务，但引入部分成功。

判断哪些副作用值得 Outbox，不要“一律上 MQ（消息队列）”：

| 副作用 | 丢失是否可由客户端恢复 | 建议 |
|---|---:|---|
| WebSocket UI 刷新 | 通常可以，HTTP 可重拉 | 允许丢，但要统计与断线重同步 |
| Conversation 列表快照 | 不一定；会持续显示旧值 | 应保证可重算或纳入同事务 |
| Webhook | 外部系统可能永远不知道 | 若承诺可靠投递，应使用 delivery/outbox |
| Automation | 可能改变分配、状态或回复 | 按规则重要性决定持久化与幂等 |
| SLA | 影响承诺与告警 | 以 DB 状态为源，确保可重扫与原子转移 |
| 通知 | 部分可容忍，部分合规告警不可丢 | 按通知类型分级 |

Outbox 解决的是“业务状态提交与待发布事件原子写入”，不自动解决消费者重复。消费者仍需 event ID、幂等记录、顺序规则、重试和死信。

## 4. 多实例审查

把服务从一个实例扩到两个实例时，逐项分类：

| 组件 | 当前共享状态 | 双实例主要问题 | 常见措施 |
|---|---|---|---|
| HTTP/RBAC | PostgreSQL + Redis | cache（缓存）短暂不一致 | 精确失效、TTL（生存时间）、版本号 |
| outgoing scanner | DB pending + 进程内 sync.Map | 重复领取 | DB claim + lease |
| incoming receiver | 各实例 Inbox receiver | 邮件重复消费 | 单活/leader、协议游标、唯一键 |
| Automation timed trigger | 每实例 ticker | 规则重复执行 | leader election、DB job claim、动作幂等 |
| SLA evaluation | DB 状态 + 每实例 ticker | 重复扫描/竞争更新 | 条件更新、行锁、批量 claim |
| SLA notifications | DB 未处理行 | 重复发送 | claim/lease + 幂等通知 ID |
| Webhook | 进程内 queue | 事件只存在触发实例且会丢 | transactional outbox + delivery worker |
| WebSocket Hub | 进程内连接 map | A 实例更新无法推 B 实例连接 | Redis Pub/Sub（发布/订阅）/NATS（消息通信系统）+ 本地 fan-out（扇出广播） |
| AI Agent | 进程内 running/pending map | 同会话并行响应 | DB/Redis 分布式租约 + 运行代次 |
| 内存向量索引 | 每实例副本 | 内存翻倍、更新短暂不同步 | 事件失效、版本切换或外部向量库 |

粘性会话只能帮助 WebSocket 连接落到稳定实例，不能解决 HTTP 在其他实例产生事件后的跨实例广播，也不能解决后台任务重复执行。

## 5. 认证、授权与安全边界

### 5.1 当前成立的事实

- Session 保存在 Redis；Cookie 为 HttpOnly（禁止脚本读取）、SameSite=Lax（限制跨站携带），并按环境设置 Secure（仅经 HTTPS 发送）。
- CSRF Cookie 可由前端读取，用 header 做 double submit；当前只保护 POST/PUT/DELETE，路由表暂无 PATCH。
- API Secret（接口密钥）数据库存 SHA-256（安全哈希算法）；旧 bcrypt（自带盐的慢速密码哈希算法）格式会在成功验证后迁移。
- 路由动作权限与 Conversation 资源权限分层。
- 搜索结果、Agent WebSocket 订阅和 Agent AI 工具另做资源过滤。
- 角色权限变更会清缓存；权限移除还会断开相关 Agent WebSocket。
- Widget WebSocket 允许跨域，但 Join 后用 session token、Inbox 和 Contact 身份约束。

### 5.2 需要业务确认的授权策略

- Conversation/Contact 自定义属性更新使用 `auth`，只有资源可读检查，没有独立动作权限。
- Draft 是用户私有协作状态，使用 `auth` 加资源可读检查是否足够？角色没有 `messages:write` 时能否保存 reply draft？
- Macro route 使用 `auth`，但每个 action 会映射到具体 permission；要测试部分成功与审计记录。
- Agent typing 允许已认证 Agent 对任意 UUID 发装饰性事件，这是源码明确接受的风险；若威胁模型变化，应加低成本授权缓存或订阅约束。

### 5.3 需要优先修正的安全工程问题

1. 日志不记录 CSRF token、Authorization、Webhook signature、OTP（一次性密码）、AI 工具认证头和消息正文。
2. 为日志建立字段分级、脱敏、保留期和访问审计；debug 不能长期用于生产。
3. 托管/多租户部署显式启用 SSRF Guard，覆盖 DNS rebinding（域名系统重新绑定攻击）、重定向和云元数据地址。
4. pprof 只绑定 loopback 或独立管理网，并在反向代理层认证。
5. 明确可信代理列表，不能无条件相信客户端伪造的真实 IP Header。
6. 密码重置、OIDC state（OpenID Connect 认证状态参数）、媒体签名 URL、Widget token、OTP 都要验证 TTL、单次消费、重放和暴力尝试限制。

## 6. 流量、容量与背压场景

### 场景 A：营销活动带来 10 倍 Live Chat 流量

先观察而不是先扩 Worker：

- HTTP P50/P95/P99（50%、95%、99% 请求不超过的延迟分位值）、状态码和请求体大小。
- DB pool 等待时间、活跃连接、慢 SQL、锁等待。
- incoming/outgoing/Automation/Webhook/Notification/AI queue 长度和 drop 数。
- 每个 Inbox 的发送耗时、失败率、超时率。
- WebSocket 连接数、每连接 send queue 使用率、丢帧和断开数。

当前代码大多只有日志，没有上述标准运行指标。增加指标时避免把 conversation UUID、email、URL 等高基数字段放进 label。

### 场景 B：SMTP（简单邮件传输协议）持续超时

当前固定 Worker 会被慢调用占住，失败后消息标 failed，没有 Conversation 层自动指数退避。需要确认 SMTP client timeout、连接池隔离、最大并发、Retry 用户体验和告警阈值。若自动重试，必须有最大次数、退避、jitter 和死信，避免对故障 SMTP 发起重试风暴。

### 场景 C：Webhook 下游返回 1 GiB 响应

HTTP Client 有总超时和连接阶段超时，但 `io.ReadAll` 没有响应体上限。应使用 `io.LimitReader` 或只读取固定大小的诊断片段，并记录 `truncated=true`。失败响应正文也要脱敏。

### 场景 D：Redis 故障

- Session 认证失败，管理端请求不可用。
- 公开接口限流当前 fail-open。
- Widget page visit、在线状态、AI OTP 等临时能力受影响。
- PostgreSQL 中的核心 Conversation/Message 仍存在。

这不是简单的“Redis 是缓存所以故障无影响”；它同时承载 Session 和多种业务临时状态。恢复目标应按能力分级。

### 场景 E：PostgreSQL 连接池耗尽

默认 `max_open=30`，HTTP、消息、SLA、Automation、AI、清理任务共享同一个 pool。增加 Worker 可能只会增加排队和超时。应同时测 DB service time、连接等待、事务时长、批量大小和下游并发，依据 Little's Law 做粗略容量估算。

这个场景还会触发一个具体错误路径：[`GetConversationMessages`](../../internal/conversation/message.go#L350-L356) 与 [`GetConversations`](../../internal/conversation/conversation.go#L663-L669) 在判断 `BeginTxx` 是否成功之前就注册 `defer tx.Rollback()`。如果 Begin 因连接耗尽返回 `(nil, error)`，函数返回阶段可能在 nil Transaction 上 Rollback 并 panic。第一优先级是把 `defer` 移到错误检查之后并增加故障注入回归测试；随后再用连接等待指标和有界 Worker 并发解决容量根因。

## 7. 可观测性与故障定位

建议先建立四类信号：

1. RED：请求 Rate、Errors、Duration。
2. Worker：queue depth、enqueue/drop、oldest age、processing duration、success/failure/retry。
3. 外部依赖：PostgreSQL/Redis/SMTP/IMAP（互联网邮件访问协议）/S3（对象存储服务）/OIDC/Webhook/AI 的耗时与错误分类。
4. 业务不变量：pending 最老年龄、failed 消息数、未处理 SLA 通知数、Webhook dead 数、AI handoff 率。

日志至少关联：request ID、conversation UUID、message UUID、inbox ID、task/event ID、attempt；不要关联密钥或完整正文。一次消息跨 HTTP、DB scanner、Worker 和 Webhook 时，最好用稳定 correlation/event ID，而不是只靠时间戳拼日志。

pprof（Go 性能剖析工具）用于 CPU、heap（堆内存）、goroutine（轻量级并发单元）、mutex（互斥锁）和 block profile（阻塞剖析）；它不是业务指标，也不能代替链路追踪。性能分析必须保留数据量、流量模型、执行计划和前后对比。

## 8. 数据库、迁移与灾备

面试常见追问不会停在“用了 PostgreSQL”：

- migration 是否可在已有大表上执行，建索引是否会长时间锁表？
- 新旧版本同时运行时，schema 是否前后兼容？
- destructive migration 如何备份、验证和前滚？
- PostgreSQL、Redis、uploads/localfs 或 S3 各自备份什么？恢复顺序是什么？
- 恢复到某个时间点后，外部已发送邮件和回滚后的 DB 状态如何对账？
- 数据删除是否覆盖 Message、附件、搜索索引、AI embeddings、日志和备份保留期？

LibreDesk 是自托管单租户产品，schema 没有 tenant_id。这降低了租户隔离复杂度；如果改造成 SaaS（软件即服务），多租户授权、唯一约束、索引前缀、配额、加密和数据迁移都需要重新设计，不能只加一个 tenant_id 字段。

## 9. 业务场景推演模板

每个场景都按六步回答：

```text
用户动作：谁在什么渠道做了什么？
入口与权限：HTTP/WS/Worker 入口，认证、动作权限、资源权限。
核心状态：哪些表、状态机和事务发生变化？
副作用：广播、邮件、Webhook、Automation、SLA、AI、通知。
故障窗口：在哪一步可能重复、丢失、乱序、部分成功或超时？
措施与验证：当前措施、候选方案、测试/指标/回滚证据。
```

填写时把每一步变成可点击源码证据。例如 outgoing 消息至少要链接 [`handleSendMessage`](../../cmd/messages.go#L177-L269)、[`InsertMessage`](../../internal/conversation/message.go#L579-L668)、[`get-outgoing-pending-messages`](../../internal/conversation/queries.sql#L697-L738) 和 [`sendOutgoingMessage`](../../internal/conversation/message.go#L147-L224)，而不是只写文件名。

建议至少推演下面十个场景：

1. 两个 Agent 同时认领同一团队会话。
2. 同一封邮件被两个接收器同时拉取。
3. SMTP 接受邮件后进程立刻崩溃。
4. 访客离线时 Agent 发送 Live Chat 回复。
5. Automation 自动回复再次触发消息更新规则。
6. 角色权限刚被移除，但用户仍保持旧页面和 WebSocket。
7. 两个实例同时发送同一 SLA 通知。
8. Webhook 域名解析到私网地址并返回超大响应。
9. AI 工具运行中人工 Agent 接管会话。
10. Embedding 模型/维度切换时旧索引仍被查询。

其中最适合作为运行证据的六项是：不可达 SMTP 下的 pending→failed、测试 PostgreSQL 关闭/开启时的 SKIP 对照、无权 UUID 的 HTTP/搜索/WebSocket 三入口、超过 128 帧的慢 Client、两个实例领取同一 pending ID、AI Run 中途人工接管。每个实验保存前置数据、配置、精确命令、SQL 前后状态、关联日志、预期和实际差异；否则只能标记为风险推演，不能写成已复现事故。

## 10. 面试深挖题与回答要点

### 架构与边界

1. 为什么是模块化单体？答：领域协作紧密、自托管交付简单、进程内接口成本低；代价是资源竞争和多实例 Worker 语义。
2. `cmd` 是 Controller 层吗？答：主要做 HTTP 适配和组合，但部分业务校验仍在 Handler；不能机械套三层架构。
3. 为什么接口定义在使用者附近？答：最小依赖、便于 mock、避免依赖完整实现；启动仍需要手工装配和 setter 解决环。
4. 什么时候拆 Worker？答：需要独立扩缩容/故障隔离且已建立持久事件、幂等和可观测性时，不因文件多就拆。

### 数据与一致性

5. 为什么 Message 与 Conversation 都保存消息信息？答：Message 是历史事实，Conversation 是高频列表快照，以写放大换读性能。
6. `InsertMessage` 保证了什么？答：只原子保证 Message 与 media 关联；commit 后副作用不是同一事务。
7. 为什么不用跨 SMTP 的分布式事务？答：SMTP 不参与 2PC，长事务也不可取；用幂等、状态机、重试与对账。
8. `source_id` 去重有什么漏洞？答：普通索引 + 先查后写存在并发竞态，应由数据库唯一性兜底。
9. JSONB 什么时候合适？答：低频扩展结构；高频过滤、外键与强约束字段应规范化。

### 并发与可靠性

10. Worker Pool 是否等于背压安全？答：只限制消费者并发；当前扫描查询和批量结果仍无界，生产者还会阻塞。
11. `sync.Map` 能否支持多实例？答：不能，只是进程内排除正在处理 ID。
12. 怎样保证 shutdown？答：先停生产、可取消的 enqueue、等待生产者、关闭 channel、限时排空消费者，测试满队列和慢下游。
13. WebSocket 为什么允许丢普通帧？答：实时层是提示通道，事实在 HTTP/DB；慢客户端不能拖垮 Hub。
14. 粘性连接能否解决广播？答：不能，其他实例产生的事件仍需跨实例总线。

### 安全

15. CSRF、SameSite、CORS（跨源资源共享）、WebSocket Origin（连接来源）各解决什么？必须分别解释，不能混为一谈。
16. API Secret 为什么可用 SHA-256 而密码用 bcrypt？答：Secret 是高熵随机值，密码低熵且可猜测，需要昂贵 KDF（密钥派生函数）。
17. SSRF Guard 为什么“接入了”仍不够？答：样例默认关闭，且要验证 DNS、重定向、allowlist 与部署信任模型。
18. AI Agent 的新攻击面是什么？答：prompt injection、工具越权、数据外泄、恶意响应、PII 日志和成本滥用。

### 性能与运维

19. pending 扫描先优化 SQL 还是加 Kafka？答：先量化积压、查询计划和交付需求；有界 claim 通常是较小改造，可靠跨域事件才考虑 MQ。
20. 为什么增加 DB pool 可能更慢？答：数据库 CPU/IO/锁已饱和时更多连接只增加竞争和排队。
21. pprof 能回答什么、不能回答什么？答：能定位进程资源热点，不能给出业务成功率、队列丢弃或跨服务链路。
22. 怎样证明优化有效？答：固定数据和流量模型，保留 baseline、执行计划/P95/资源、单变量改动和回归测试。

## 11. 改进路线图

### 第一阶段：低成本高收益

- 删除 CSRF token 日志；对 Webhook/AI 日志做正文脱敏。
- 限制 Webhook 响应体，记录截断标志。
- 增加 queue depth/drop/oldest age、外部调用耗时和 pending age 指标。
- 为 shutdown、满队列、慢客户端和慢外部服务增加并发测试。
- 从 Assignee 候选中过滤 Disabled AI Assistant，并在禁用时迁移或转交已分配 Open Conversation。
- 把 SSRF、pprof、可信代理和 debug 日志加入部署检查表。

### 第二阶段：数据正确性

- outgoing 使用有界 DB claim + processing lease + attempt。
- 为 incoming 设计作用域正确的 source unique key，并清理历史重复。
- SLA notification 增加 claim/lease、notification idempotency key，并把各通知通道的真实投递结果纳入状态机。
- 对 Webhook 承诺可靠投递时，引入 delivery/outbox、重试和死信。

### 第三阶段：规模化

- WebSocket 跨实例 Pub/Sub。
- 对 Automation timed trigger、AI Agent、清理任务做 leader/claim 分类。
- 优化深分页、热点列表和 pending partial index，保留 Explain/压测证据。
- 当向量规模和 P95 数据证明需要时，再评估 pgvector/HNSW 或外部向量服务。

每一阶段都必须同时写清楚迁移、回滚、兼容性、指标和故障注入。只实现 happy path 的“架构升级”不具备面试说服力。

## 12. 审查证据索引

复核时优先按函数/SQL 名搜索：

- 启动与关闭：`cmd/main.go:main`、`cmd/init.go:initConfig/loadSettings`
- 认证授权：`cmd/middlewares.go:authenticateUser/perm/tryAuth`、`internal/authz/authz.go:CanReadAssignment`
- 消息：`internal/conversation/message.go:Run/InsertMessage/sendOutgoingMessage/ProcessIncomingMessage`
- 消息 SQL：`get-outgoing-pending-messages`、`insert-message`、`message-exists-by-source-id`
- WebSocket：`internal/ws/client.go`、`internal/ws/ws.go`、`cmd/widget_ws.go`
- Automation：`internal/automation/automation.go:Run/EvaluateConversationUpdateRules/Close`
- SLA：`internal/sla/sla.go:RecomputeConversationNextSLADeadline/SendNotifications`
- Webhook：`internal/webhook/webhook.go:TriggerEvent/deliverSingleWebhook`
- AI 基础层：`internal/ai/openai.go`、`embedding.go`、`embedsource.go`、`tools.go`、`agent.go:RunAgentWithTools`、`copilot.go`
- 自主 Agent：`internal/aiagent/aiagent.go`、`worker.go`、`prompt.go`、`tools.go`、`otp.go`、`faq.go`
- Schema 与索引：`schema.sql`
- 测试入口：`Makefile:test/test-db`、`frontend/package.json`

如果结论无法落到上述证据、运行结果或明确的业务假设，就把它标成待验证，而不是写成项目事实。

提交改造方案前，再沿当前业务段落逐项确认：所有 HTTP/非 HTTP 入口、身份/动作/资源权限、表与命名 SQL、commit 前后副作用、队列满和 context 取消、崩溃与双实例、外部 timeout/响应上限/幂等键、日志敏感字段、测试 SKIP、迁移与回滚。面试表达按“源码事实 → 故障窗口 → 业务影响 → 候选方案 → 验证结果”展开。
