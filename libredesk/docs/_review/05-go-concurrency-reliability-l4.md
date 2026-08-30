# LibreDesk 异步任务、Go 并发模型与可靠性源码学习

## 1. 这个模块在 LibreDesk 中解决什么问题

本章承接[领域状态](02-domain-conversation-message-state-machine-l4.md)、[数据库事务](03-postgresql-sql-transactions-concurrency-l4.md)与[HTTP 请求边界](04-http-auth-authorization-api-layer-l4.md)，继续追问“HTTP 已返回之后，后台工作如何完成”。Message、SLA 与 Webhook 分别选择“数据库持久状态 + 扫描器”“周期调度器”和“纯内存队列”，这些选择直接决定背压、重试与多实例行为。

## 本章核心源码

| 优先级 | 文件 / Symbol | 为什么必须读 |
|---|---|---|
| P0 | [`conversation.Manager.Run` → `message.go:55`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:55:1) | Message scanner、channel 与 Worker 的连接点 |
| P0 | [`sendOutgoingMessage` → `message.go:147`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:147:1) | 慢速外部 I/O 与最终状态更新 |
| P0 | [`get-outgoing-pending-messages` → `queries.sql:697`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:697:1) | 持久待办如何被后台重新发现 |
| P0 | [`sla.Manager.Run` → `internal/sla/sla.go:517`](vscode://file/D:/codes/dev_proj/libredesk/internal/sla/sla.go:517:1) | 数据库时间状态如何被周期判断 |
| P0 | [`webhook.TriggerEvent` → `webhook.go:256`](vscode://file/D:/codes/dev_proj/libredesk/internal/webhook/webhook.go:256:1) | 非阻塞入队和过载策略 |
| P0 | [`webhook.Run` → `webhook.go:299`](vscode://file/D:/codes/dev_proj/libredesk/internal/webhook/webhook.go:299:1) | Webhook Worker 生命周期和排空行为 |
| P1 | [`message.*` 配置 → `config.toml:97`](vscode://file/D:/codes/dev_proj/libredesk/config.toml:97:1) | Worker 数、队列容量与扫描间隔的来源 |

## 2. 一张图看懂整体机制

```text
Message：DB pending → scanner → 有界 channel（满时阻塞）→ Worker → sent/failed
SLA：    DB deadline → ticker 周期判断 → 状态更新 / 通知
Webhook：业务事件 → 有界 channel（满时丢弃）→ Worker → 外部 HTTP
AI Agent：进程内任务队列 → Worker；入队失败时由调用链决定降级或报错
```

## 3. 必须先理解的核心概念

- **背压（Backpressure）**：下游处理速度跟不上生产速度时，用阻塞、拒绝或丢弃限制新任务进入；三条链的策略并不相同。
- **工作池（Worker Pool）**：多个 goroutine 从同一队列取任务，以受控并发执行慢速 I/O。
- **进程内队列（Process-local Queue）**：只存在于当前进程内存中的 channel；进程退出后队列内容不会保留，也不能协调其他实例。
- **任务领取（Claim）与租约（Lease）**：领取用于确保任务只由一个 Worker 处理，租约让领取权在 Worker 崩溃后过期；当前 Message pending 扫描没有跨实例 claim/lease。
- **按键串行化（Per-key Serialization）**：以 `conversation_id` 等业务 Key 为粒度让同一 Key 串行、不同 Key 并行；当前 Message Worker 没有采用这种顺序控制。
- **排空（Drain）**：停止接收新任务后继续处理队列中已有任务；等待 Worker 退出不一定等于队列已被排空。
- **分发器（Dispatcher）**：把一个领域事件交给数据库、WebSocket、Email 等多个下游；调用分发器成功不一定等于所有通道完成投递。

## 4. 源码阅读路线

**Message：** [`Run`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:55:1) → [`sendOutgoingMessage`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:147:1) → [`UpdateMessageStatus`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:416:1)。

**SLA：** [`Manager.Run`](vscode://file/D:/codes/dev_proj/libredesk/internal/sla/sla.go:517:1) → [`SendNotifications`](vscode://file/D:/codes/dev_proj/libredesk/internal/sla/sla.go:560:1) → [`apply-sla SQL`](vscode://file/D:/codes/dev_proj/libredesk/internal/sla/queries.sql:39:1)。

**Webhook：** [`TriggerEvent`](vscode://file/D:/codes/dev_proj/libredesk/internal/webhook/webhook.go:256:1) → [`Run`](vscode://file/D:/codes/dev_proj/libredesk/internal/webhook/webhook.go:299:1) → [`deliverWebhook`](vscode://file/D:/codes/dev_proj/libredesk/internal/webhook/webhook.go:337:1)。


## 5. 从全局看四类并发与调度模型

```text
OS signal
  └─ signal.NotifyContext (cmd/main.go:148)
       ├─ HTTP server goroutine
       ├─ Inbox receiver goroutines
       │    └─ IMAP ticker → mailbox scan → incomingMessageQueue → incoming workers → PostgreSQL
       ├─ Immediate in-memory queues
       │    ├─ Automation taskQueue → N workers
       │    ├─ Webhook deliveryQueue → N workers → HTTP endpoint
       │    ├─ Notification messageChannel → N workers → email provider
       │    └─ AI Agent queue/miningQueue → per-conversation coordination → LLM/tools
       ├─ Durable-state + memory-dispatch hybrid
       │    └─ conversation_messages(status=pending)
       │         → 50ms DB scan → outgoingMessageQueue → N workers → Inbox.Send
       ├─ DB-backed periodic schedulers
       │    ├─ SLA applied/event evaluation
       │    └─ scheduled_sla_notifications scan → Dispatcher → DB/WS/email queue
       └─ Direct ticker/background loops
            ├─ autoassign / unsnooze / continuity / availability
            ├─ draft/media/notification/search-log cleanup
            ├─ AI embedding reconcile
            └─ update check / importer cleanup
```

进程级根取消信号由 [`cmd/main.go:148`](vscode://file/D:/codes/dev_proj/libredesk/cmd/main.go:148:1) 的 `signal.NotifyContext` 创建。[`cmd/main.go:274`](vscode://file/D:/codes/dev_proj/libredesk/cmd/main.go:274:1) 用独立 goroutine 启动主要后台模块；[`cmd/main.go:370`](vscode://file/D:/codes/dev_proj/libredesk/cmd/main.go:370:1) 收到取消后依次关闭 HTTP、AI Agent、AI、Inbox、Automation、Autoassigner、Notification、Webhook、Conversation、SLA、Importer、DB、Redis。

【代码分析】LibreDesk 不是一个统一 Queue 抽象驱动的系统，而是至少四种并发/调度语义并存：

1. PostgreSQL（数据库）持久状态 + Ticker（周期触发器）扫描 + channel（通道）分发；
2. 纯进程内 buffered channel（有缓冲通道）；
3. PostgreSQL 到期记录 + 周期扫描，但不经过本模块的 worker pool；
4. 不经队列、每个业务对象直接启动 goroutine，并用 Semaphore（信号量）或 WaitGroup（等待组）约束。

因此“LibreDesk 的任务可靠性”不能统一回答，必须逐条链路说明持久性、满队列策略、重复执行窗口和停机语义。

---

### 5.1 主要后台机制分类

### 进程内有界队列

| 机制 | Producer（生产者） | Queue / 容量 | Worker | 满时行为 | 持久化 |
|---|---|---|---|---|---|
| Conversation incoming | Email IMAP `processFullMessage` → `EnqueueIncoming` | `chan IncomingMessage`；`message.incoming_queue_size=5000` | `incoming_queue_workers=10` | 非阻塞返回 error，IMAP 调用链收到 error | enqueue task 没有独立持久表；最终 Message 由 worker 写 DB |
| Conversation outgoing dispatch | DB scanner | `chan Message`；`message.outgoing_queue_size=5000` | `outgoing_queue_workers=10` | scanner 使用阻塞 send，形成进程内背压 | 是，`conversation_messages.status='pending'` |
| Automation | 会话创建/更新事件及小时 Ticker | `chan ConversationTask`；常量 `MaxQueueSize=10000` | `automation.worker_count=10` | 业务事件非阻塞丢弃并记 Warn；小时任务使用阻塞 send | 规则在 DB，任务本身不持久 |
| Webhook | Conversation/Message 等业务方法 | `chan DeliveryTask`；`webhook.queue_size=10000` | `webhook.workers=5` | 非阻塞丢弃并记 Warn；调用方无 error | Webhook 配置在 DB，投递任务不持久 |
| Notification email | `Dispatcher.sendEmail` 等 | `chan notifier.Message`；`notification.queue_size=2000` | `notification.concurrency=2` | `Send` 返回 error；Dispatcher 只记录日志 | 不持久 |
| AI Agent response | `HandleConversationEvent` | `chan int`；`ai_agent.queue_size=1000` | 默认 10 | 满时清理 in-flight 标记，并另起 goroutine 走人工接管 | 任务不持久；会话状态在 DB |
| AI FAQ mining | `HandleConversationResolved` | `miningQueue chan int`；同 queue size | `min(worker, 2)` | 丢弃并记 Warn | 任务不持久 |

证据：[`internal/conversation/conversation.go:84-108,270-290`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/conversation.go:84:1)；[`internal/automation/automation.go:28-29,41-64,90-104,287-330`](vscode://file/D:/codes/dev_proj/libredesk/internal/automation/automation.go:28:1)；[`internal/webhook/webhook.go:39-71,99-110,255-295`](vscode://file/D:/codes/dev_proj/libredesk/internal/webhook/webhook.go:39:1)；[`internal/notification/notification.go:44`](vscode://file/D:/codes/dev_proj/libredesk/internal/notification/notification.go:44:1)；[`internal/aiagent/aiagent.go:80-98,120-136`](vscode://file/D:/codes/dev_proj/libredesk/internal/aiagent/aiagent.go:80:1)；[`config.toml:97-139`](vscode://file/D:/codes/dev_proj/libredesk/config.toml:97:1)。

### DB 状态驱动的周期机制

| 机制 | 周期 | scan/select | process | 多实例互斥证据 |
|---|---:|---|---|---|
| Outgoing message scanner | 配置，默认 50ms | 所有 `pending/outgoing/non-private`，仅排除本进程 `sync.Map` 中 ID | 灌入本进程 channel 后调用 `Inbox.Send` | 当前查询没有 claim、行锁或 lease（租约） |
| SLA applied evaluation | 配置，默认 5m | 只选 deadline 已到或业务结果已产生的 pending SLA | 写 met/breached、关闭已完成 SLA、重算 deadline | 重算路径对 Conversation 行 `FOR UPDATE`；scan/状态领取没有实例互斥 |
| SLA event evaluation | 配置，默认 5m | 到期或已有 `met_at` 的 pending event | 写 event 状态、生成 breach notification | scan/通知插入没有 claim/唯一键 |
| SLA notification sender | 固定 20s | `send_at <= NOW() AND processed_at IS NULL` | Dispatcher 发送，随后 `processed_at=NOW()` | 查询没有 claim、`SKIP LOCKED` 或 lease |
| Autoassigner | 配置，默认 5m | 查询未分配 Conversation | round-robin 后条件 UPDATE claim | 有条件 UPDATE：仅 `assigned_user_id IS NULL AND assigned_team_id=$3` |
| Unsnoozer | 配置，默认 5m | SQL 更新到期 snooze | 广播变更 | 本章仅作对比，不展开多实例副作用 |
| Continuity email | 配置，默认 5m | 遍历 livechat inbox，查 offline/unread | 组装并发送 continuity email | 当前没有跨实例互斥机制 |

Autoassigner 是一个重要反例：[`internal/conversation/queries.sql:436`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:436:1) 的条件 UPDATE 与 `RowsAffected` 检查，使两个实例同时看到同一未分配会话时，只有仍满足条件的更新成功。这个机制不能自动外推到 Message、SLA 或 Webhook。

### 直接 Ticker / Timer 后台循环

| 机制 | 入口与周期 | 主要资源 | 取消/等待 |
|---|---|---|---|
| Draft cleaner | `RunDraftCleaner`；每 2h | DB delete | 监听根 ctx；未纳入 Conversation 的 `wg` |
| Media orphan cleaner | `DeleteUnlinkedMedia`；启动等待 60s，之后每 12h | DB + media storage | 监听 ctx；无独立 Close/join |
| User availability | `MonitorUserAvailability`；60s | DB/cache + offline callback | 监听 ctx；无独立 join |
| User notification cleaner | 启动等待 60s，之后 24h | DB delete | 监听 ctx；无独立 join |
| Help-center search log cleaner | Timer 60s，之后 24h | DB delete | 监听 ctx；无独立 join |
| AI embedding reconcile | 启动即执行，之后 `reconcileInterval` | DB、embedding provider、内存 index | `wg` 跟踪 reconcile 和 embed jobs；`Close` 等待 |
| Importer cleanup | 1h | 内存 job 状态 | Importer 私有 ctx cancel + `wg` |
| Update checker | 启动即检查，之后 1h | 外部 HTTP | 根 ctx 没有传入 `checkUpdates`；当前启动与退出链中未见 Close/join |
| Email IMAP polling | 每个 inbox config 一个 goroutine；默认回退 5m | IMAP + incoming queue | per-receiver context cancel；Inbox `wg` 与 Email `wg` 等待 |

### 同步原语按职责分类

- 生命周期防 send-on-closed：Conversation、Automation、Webhook、Notification、AI Agent 的 `closed` + `Mutex/RWMutex`。
- worker 生命周期：上述模块以及 SLA、Inbox、Email、Importer、AI 的 `sync.WaitGroup`。
- 进程内去重/串行化：Conversation 的 `sync.Map` 只记录本进程正在发送的 message ID；AI Agent 的 `mu + inflight/pending` 对 Conversation ID 串行化并合并一次后续触发；Automation 的 `suppressedMu` 抑制自身动作的同步回声。
- 共享缓存/配置：Auth、User、Template、Inbox、Automation rules、AI index 等使用 `Mutex/RWMutex`。
- 一次性关闭/初始化：Livechat `atomic.Bool + sync.Once`，AI tokenizer `sync.Once`。
- 无锁版本/配置标记：`cmd.App.consts atomic.Value`、AI `tagGen atomic.Uint64`。
- AI embedding：`embedSem chan struct{}` 限制并发，generation（代际号）阻止旧任务覆盖新任务，`reindexMu/reconcileMu/genMu` 保护重建与提交顺序。

【代码分析】锁在这里主要保护“同一进程内的共享内存和 channel 生命周期”。除 SQL 条件更新/约束/行锁明确介入的路径外，它们不提供跨 LibreDesk 实例的互斥。

---

## 6. 核心链路一：Outgoing Message 的持久状态与外部 I/O

### 6.1 为什么公开回复不能同步等待外部 I/O

把 Agent（客服）回复先保存为可见的 Conversation Message，再异步投递到 Inbox Channel（收件箱通道）：Email 走 SMTP，Livechat 走已连接客户端。它同时维护 message status、Conversation 回复时间、SLA 和 Automation/Webhook 副作用。

### 6.2 从 HTTP 到 Inbox.Send 的连续执行链

主入口：

```text
POST /api/v1/conversations/{cuuid}/messages
  → cmd/handlers.go:73 perm(handleSendMessage, "messages:write")
  → cmd/messages.go:176 handleSendMessage
  → enforceConversationAccess / inbox 与输入检查
  → internal/conversation.Manager.QueueReply
  → Manager.InsertMessage
  → PostgreSQL INSERT conversation_messages(status='pending') + media link transaction
  → HTTP 返回已落库 Message

cmd/main.go:276 go conversation.Run(...)
  → 50ms Ticker
  → GetOutgoingPendingMessages
  → outgoingProcessingMessages.Store(message.ID)
  → outgoingMessageQueue <- message
  → N × MessageSenderWorker
  → sendOutgoingMessage
  → Inbox.Send(OutboundMessage)
      ├─ Email.Send → SMTP pool
      └─ LiveChat.Send → connected client channel
  → UpdateMessageStatus(sent/failed)
  → reply timestamps / SLA / WebSocket / Automation / Webhook
```

人工失败重试入口：

```text
PUT /api/v1/conversations/{cuuid}/messages/{uuid}/retry
  → handleRetryMessage
  → 验证 sender/status/owner/conversation
  → MarkMessageAsPending
  → 下一次 DB scan 再次发现
```

关键 Symbol：

- [`cmd/messages.go:141`](vscode://file/D:/codes/dev_proj/libredesk/cmd/messages.go:141:1)：`handleRetryMessage`。
- [`cmd/messages.go:176`](vscode://file/D:/codes/dev_proj/libredesk/cmd/messages.go:176:1)：`handleSendMessage`。
- [`internal/conversation/message.go:503`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:503:1)：`QueueReply`。
- [`internal/conversation/message.go:578`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:578:1)：`InsertMessage`。
- [`internal/conversation/message.go:53`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:53:1)：`Run`。
- [`internal/conversation/message.go:131`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:131:1)：`MessageSenderWorker`、`sendOutgoingMessage`。
- [`internal/inbox/inbox.go:54`](vscode://file/D:/codes/dev_proj/libredesk/internal/inbox/inbox.go:54:1)：`MessageHandler`、`Inbox` interface（接口）。
- [`internal/inbox/channel/email/smtp.go:107-...`](vscode://file/D:/codes/dev_proj/libredesk/internal/inbox/channel/email/smtp.go:107:1)：`Email.Send`。
- [`internal/inbox/channel/livechat/livechat.go:198-...`](vscode://file/D:/codes/dev_proj/libredesk/internal/inbox/channel/livechat/livechat.go:198:1)：`LiveChat.Send`。

### 6.3 Message 如何穿过数据库与队列

`conversation.Manager` 包含：

```text
incomingMessageQueue       chan models.IncomingMessage
outgoingMessageQueue       chan models.Message
outgoingProcessingMessages sync.Map
closed                     bool
closedMu                   sync.RWMutex
wg                         sync.WaitGroup
```

配置：[`config.toml:97-107`](vscode://file/D:/codes/dev_proj/libredesk/config.toml:97:1) 中 outgoing/incoming worker 都是 10，scan interval 是 50ms，两个 channel capacity 都是 5000；初始化在 [`cmd/init.go:313`](vscode://file/D:/codes/dev_proj/libredesk/cmd/init.go:313:1) 与 [`internal/conversation/conversation.go:288`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/conversation.go:288:1)。

核心表：[`schema.sql:302-324`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:302:1) 的 `conversation_messages`：

- `uuid UNIQUE`；
- `status message_status NOT NULL`，枚举含 `received/sent/failed/pending`；
- FK（Foreign Key，外键）`conversation_id`、`sender_id`；
- `source_id` 只有普通索引，没有 UNIQUE constraint（唯一约束）；
- `status` 有单列索引。

核心 SQL：

- `insert-message`：[`internal/conversation/queries.sql:828`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:828:1)。
- `get-outgoing-pending-messages`：`697-729`，筛选 `status='pending' AND type='outgoing' AND private=false`，只排除传入的本进程 processing IDs；没有 `ORDER BY`、`LIMIT`、claim、锁或状态迁移。
- `update-message-status`：`856-857`，按 UUID 直接写状态。

`InsertMessage` 在同一 DB transaction（数据库事务）中插入 Message 并调用 `LinkMessageMediaTx` 关联附件，commit 后才更新 Conversation 派生字段、广播和触发 Webhook。

### 6.4 pending、sent、failed 的提交点与不变量

#### 状态机

```text
QueueReply
  → pending
      ├─ Inbox.Send error（ErrClientNotConnected 除外） → failed
      │      └─ 通过受权限约束的 retry API → pending
      └─ Inbox.Send nil 或 ErrClientNotConnected → sent
```

private note 在 `InsertMessage` 中被直接改成 `sent`，不进入 outgoing worker。普通 Agent reply 以 `pending` 入库。外部发送错误被写成 `failed`；源码仅提供人工 retry API，没有在这条 worker 链路中执行自动 backoff/retry。

`livechat.ErrClientNotConnected` 被 `sendOutgoingMessage` 特判为非失败，随后仍更新为 `sent`。这是当前状态语义，不等同于“客户端已经实时收到”。

#### 业务不变量

1. Message 与附件关联要么共同 commit，要么回滚：由 `InsertMessage` transaction 直接保证。
2. private message 不应走外部发送：`private → sent`，pending 查询也要求 `private=false`。
3. retry 只允许原发送者对同一 Conversation 下的 failed outgoing Agent message 操作：`handleRetryMessage:161-170`。
4. 同一进程的一条 message 正在处理时，不应被本进程 scanner 重复入队：`sync.Map` + SQL 的排除 ID 数组。

【代码分析】第 4 条只是 process-local（进程内）不变量，不是集群不变量；另一个实例拥有独立 `sync.Map`。

### 6.5 Worker 并发、重复窗口与停机

#### Queue 与背压

Producer 并不直接 enqueue outgoing channel。HTTP 路径同步完成 DB transaction；若 DB/附件事务失败，HTTP 返回 error；若成功，即使 worker 尚未处理，调用方也得到 Message。

scanner 向 `outgoingMessageQueue` 使用无 `select` 的阻塞 send：`m.outgoingMessageQueue <- message`。queue 满时 scanner 阻塞，这是 backpressure（背压），但背压只回传到 scanner，不回传到已经成功落库的 HTTP Producer。

#### 关键代码：用阻塞发送把压力留在后台

```go
for _, message := range pendingMessages {
    m.outgoingProcessingMessages.Store(message.ID, message.ID)
    m.outgoingMessageQueue <- message
}
```

**这段代码解决什么问题：** Worker 暂时跟不上时，scanner 不能无限制继续向内存队列灌任务。

**为什么这样写：** 普通 channel send 在容量耗尽时阻塞，形成后台背压；HTTP 请求已在此前把 `pending` 写入 PostgreSQL，所以不会被队列容量反向拖住。

**如果没有这段机制会怎样：** 无界内存任务会随积压增长；若改成直接丢弃又会失去本轮调度，但数据库中的 pending 仍可在后续扫描重新发现。

**当前工程代价：** scanner 被阻塞时不能继续扫描；取消与 `Close` 同时发生还需要验证 send-on-closed 的停机窗口。

【代码分析】由于查询没有 `LIMIT`，一次 tick 可以把全部 pending rows 读入内存，然后在第 5001 条附近阻塞灌队列；数据库仍是可靠待办来源，但本次查询结果本身也占用进程内存。是否构成实际内存或 DB 压力，需要积压实验，不能仅由配置断言为瓶颈。

#### Worker 与顺序

`Run` 启动多个 sender workers；每个 worker 对自己收到的 message 串行调用 `sendOutgoingMessage`，不同 worker 并行。

pending SQL 没有 `ORDER BY`；队列虽按 send/receive 顺序取值，但 10 个 worker 的完成顺序可能不同；没有按 `conversation_id` 的 Mutex（互斥锁）、Partition（分区）或按键串行化。

【代码分析】当前源码没有提供“同一 Conversation 的 outgoing message FIFO（先进先出）投递保证”。同一 Conversation 的两条 pending message 可以由不同 worker 并行调用 `Inbox.Send`，外部完成顺序可能反转。

#### 多实例与重复发送窗口

两个实例会各自执行同一 pending 查询；SQL 没有 claim/lease/`FOR UPDATE SKIP LOCKED`；排除列表来自各自的 `sync.Map`。

【代码分析】多实例可以把同一 message 同时交给各自 worker。这是由代码结构确定的竞争窗口；是否在某次运行中真的重复送达属于实验结果。

外部 `Inbox.Send` 成功后，`UpdateMessageStatus(sent)` 的 error 被调用方忽略。若外部发送成功而 DB status update 失败，row 仍可能保持 pending。

【代码分析】下一次扫描可能再次外发，形成典型的“外部副作用成功、内部确认失败”重复窗口。当前 outgoing 表没有 delivery attempt、lease owner、idempotency key（幂等键）或外部确认字段。

#### 失败、重试与 panic

- 自动 Retry（重试）/Backoff（退避）：当前 Message Sender Worker 及其直接调用链中未发现自动重试或退避；存在的是 `failed → 人工 retry → pending`。
- 持久队列（Persistent Queue）：不是独立队列表，而是 `conversation_messages.status='pending'` 充当持久待办状态。
- 死信（Dead Letter）：当前 Message Sender Worker 及其直接依赖中未发现隔离永久失败任务的结构。
- outgoing dedup/idempotency：当前没有 task claim 或外发幂等协议；`source_id` 不是唯一约束。
- Panic Recovery（恐慌恢复）：当前 `Run`、两个 Worker 与 `sendOutgoingMessage` 调用链中未发现局部 `recover`。

### 6.6 为什么 PostgreSQL、scanner、channel 与 Worker 同时存在

HTTP 先落库、worker 后发送，使请求成功不依赖 SMTP/客户端实时在线；进程重启后 pending row 仍能被 scanner 重新发现。`sync.Map` 避免同一实例 scanner 在慢发送期间重复灌入同一 ID。

【代码分析】这是一个小型、内嵌于模块化单体的持久状态分发器（Durable-state Dispatcher）：复用业务表避免引入独立消息代理（Broker），实现成本低；代价是领取协议、顺序语义和外部副作用确认需要自己处理。

【合理推断】该设计可能优先面向单实例自托管和低运维复杂度；源码没有设计文档直接证明这一动机。

### 面试表达

> Message 链把公开回复先持久化为 pending，再由 scanner 和 Worker 外发；数据库承担可恢复发现，channel 承担进程内并发分发，两者解决的是不同问题。

## 7. 核心链路二：SLA 的数据库时间状态与周期判断

### 7.1 SLA 为什么需要数据库时间状态

为 Conversation 应用 SLA（Service Level Agreement，服务级别协议），计算 first response / resolution / next response deadline（首次响应、解决、下次响应截止时间），周期性判断 met/breached，并在数据库中安排 warning/breach notification，之后发送站内、WebSocket 与 Email 通知。

### 7.2 从 apply 到 evaluation / notification

状态产生链：

```text
Conversation 分配 Team / Automation set SLA
  → conversation.Manager.ApplySLA
  → sla.Manager.ApplySLA
  → GetDeadlines
  → EvaluateConversationSLA(先结算旧 pending)
  → SQL apply-sla CTE：关闭/删除旧 pending，插入新 applied_slas，更新 Conversation deadline
  → createNotificationSchedule
  → INSERT scheduled_sla_notifications
```

周期判断链：

```text
cmd/main.go:281 go sla.Run(ctx, evaluation_interval)
  ├─ runSLAEvaluation Ticker
  │    → get-pending-applied-sla
  │    → evaluateSLA
  │    → update met/breached timestamps
  │    → close-settled-applied-slas
  │    → RecomputeConversationNextSLADeadline (transaction + row lock)
  └─ runSLAEventEvaluation Ticker
       → get-pending-sla-events
       → update event met/breached
       → create breach notification schedule
       → recompute deadline
```

到期通知链：

```text
cmd/main.go:282 go sla.SendNotifications(ctx)
  → 每 20s get-scheduled-sla-notifications
  → SendNotification
  → 校验 Conversation/metric 是否仍应通知
  → Dispatcher.Send
      ├─ UserNotificationManager.Create (DB)
      ├─ WebSocket broadcast
      └─ notifier.Service.Send (内存 email queue)
  → update-notification-processed
```

### 7.3 Deadline、Event 与 Notification 数据

`sla.Manager` 关键字段是各 Store、`Dispatcher`、`sync.WaitGroup` 与 DB opts；没有 SLA 任务 channel。`Run` 只为两个 evaluation loop `wg.Add(2)`。

核心表与约束：

- `applied_slas`：[`schema.sql:555-576`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:555:1)；部分唯一索引（Partial Unique Index）保证一个 Conversation 至多一个 `status='pending'` SLA。
- `sla_events`：`578-593`；记录 recurring next-response event；当前 schema 没有“每 applied SLA 至多一个未完成 next-response event”的唯一约束，该不变量由 `INSERT ... WHERE NOT EXISTS` 尝试维护。
- `scheduled_sla_notifications`：`595-609`；含 `send_at`、`processed_at`，二者各有索引；没有 claim owner/lease/attempt，也没有防同一业务通知重复插入的唯一约束。

核心 SQL：

- `apply-sla`：[`internal/sla/queries.sql:40`](vscode://file/D:/codes/dev_proj/libredesk/internal/sla/queries.sql:40:1)，单条 CTE（Common Table Expression，公共表表达式）处理旧 SLA 结算、子记录清理、新 SLA 插入和 Conversation 更新。
- `get-pending-applied-sla`：`131-149`，只读“截止已到或结果已产生”的 undecided rows。
- `lock-conversations` / `update-conversation-sla-deadline`：`172-199`，transaction 内有序 `FOR UPDATE` 后重算缓存 deadline。
- `close-settled-applied-slas`：`201-218`。
- `insert/get/update scheduled notification`：`220-265`；get 只是普通 SELECT + ORDER BY。
- `get-pending-sla-events`：`308-315`。

### 7.4 时间状态与业务不变量

```text
applied_slas.status:
pending → met | breached | partially_met

sla_events.status:
pending → met | breached

scheduled_sla_notifications:
processed_at IS NULL → processed_at = NOW()
```

关键不变量：

1. 每个 Conversation 至多一个 pending applied SLA：Schema partial unique index 直接保证。
2. SLA policy 切换时，已经产生结果的旧 SLA 要保留为历史，纯倒计时旧 SLA 可删除：`apply-sla` CTE 直接表达。
3. Conversation 的 `next_sla_deadline_at` 必须来自最新 applied SLA 的仍未结算最早 deadline：SQL lateral latest row + `LEAST`。
4. 并发重算同一 Conversation deadline 不应由旧快照覆盖新结果：`RecomputeConversationNextSLADeadline` transaction 内先 `FOR UPDATE`。
5. 已 resolved-category 或 metric 已 met 的到期通知不发送，并标记 processed：`SendNotification:608-647`。

【代码分析】不变量 1 和 4 是数据库级并发控制，能跨实例；“某条到期通知只能由一个实例发送一次”并没有等价约束。

### 7.5 周期扫描、并发与失败

#### Worker/Scheduler 语义

SLA 没有可配置 worker 数量。`Run` 固定启动两个 goroutine，分别处理 applied SLA 和 SLA events；各 loop 在单 goroutine 内串行遍历查询结果。通知发送是第三个由 `cmd/main.go` 直接启动的 goroutine，也串行遍历到期通知和 recipients。

Ticker 首次 evaluation 要等一个完整 `evaluation_interval`；`SendNotifications` 则立即扫描一次，再等待 20s。

#### 多实例

每个实例都会启动这三个 loop。pending SLA/event/notification 查询没有实例标识、advisory lock（咨询锁）、leader election（主节点选举）、claim update、`FOR UPDATE SKIP LOCKED` 或 lease。

【代码分析】

- 两个实例可以同时读取同一 pending SLA/event。虽然重复写同一 met/breached 字段的最终值通常会收敛，但两个基于旧快照的 `handleSLABreach` 都可以各自插入 notification schedule。
- 两个实例可以同时读取同一 `processed_at IS NULL` notification，在任一方标记 processed 前都调用 Dispatcher，造成重复站内/邮件通知窗口。
- 单实例也存在“Dispatcher 已产生部分副作用，`processed_at` 更新失败/进程崩溃”的重复窗口。

这三点是代码路径证明的风险窗口；没有执行双实例实验前，不写成“线上已经重复”。

#### Notification 确认（Acknowledgement，Ack）语义

`SendNotification` 调用 `m.dispatcher.Send(...)` 后立即更新 `processed_at`。`Dispatcher.Send` 没有返回值：站内通知创建失败会记日志；Email 的 `notifier.Service.Send` 若 queue full/closed 返回 error，也只在 Dispatcher 内记日志。SLA 调用方无法据此阻止 `processed_at` 更新。

【代码分析】`processed_at` 表示“已尝试交给多通道 Dispatcher”，并不严格等价于“站内、WebSocket、Email 全部成功”。尤其 Email 还有第二级纯内存 queue，入队成功也不等于 SMTP 成功。

#### 重试与幂等

- DB evaluation：下一 tick 会重新扫描仍满足 pending 条件的记录，因此 DB error 后具备“周期再尝试”的行为，但没有显式 retry 次数/backoff。
- Notification：只要 `processed_at` 仍为空，下一轮会再尝试；若已经标记 processed，即使 Email queue 后续发送失败也不会由 SLA 记录重试。
- Dedup：partial unique index 只约束 pending applied SLA；notification schedule 没有业务唯一键。
- Panic recovery：SLA goroutine 当前没有局部 panic recovery。
- Dead letter：当前没有 SLA dead letter（死信）结构。

### 7.6 为什么以 DB 为时间事实源

Deadline 和 notification schedule 都在 PostgreSQL；进程重启不会丢失尚未 processed 的计划。Ticker 查询还通过 WHERE 条件避免每轮对所有 pending SLA 做写操作。Conversation deadline 重算明确使用 transaction + row lock，并按固定 batch 限制锁范围。

【代码分析】该设计把“时间事实”放在 DB，把“何时检查”放在应用进程：易查询、易恢复，且无需单独调度基础设施。当前实现对 DB 状态一致性投入较多，但通知投递所有权（Delivery Ownership）仍是较弱的一段。

【合理推断】这条扫描链呈现类似至少一次（At-least-once-like）的行为，并可能依赖低概率并发或单实例部署；源码没有直接陈述这一权衡。

### 面试表达

> SLA 以数据库 deadline 为事实源，周期任务只负责判断到期与触发状态或通知，因此进程重启不会抹掉时间状态；但多实例是否重复处理仍取决于 SQL 的领取与状态条件。

## 8. 核心链路三：Webhook 的内存队列与外部 HTTP

### 8.1 为什么 Webhook 选择即时异步投递

Conversation/Message 发生业务事件后，异步向启用且订阅该事件的管理员配置 URL 发送签名 JSON POST；也支持只投递到指定 Webhook，以及同步执行的测试 Webhook。

### 8.2 从业务事件到外部 HTTP

```text
业务事件
  ├─ Message Insert/Status Update
  ├─ Conversation Created/Assigned/Status/Tags/Unassigned
  └─ Automation webhook action
       → webhook.Manager.TriggerEvent / TriggerWebhook
       → deliveryQueue chan DeliveryTask
       → Run 启动 N workers
       → worker → deliverWebhook
       → DB 获取目标 Webhook（单个或按事件扇出，Fan-out）
       → deliverSingleWebhook
       → JSON marshal + HMAC-SHA256 signature
       → http.Client.Do
       → 2xx success log / non-2xx or transport error log
```

直接调用证据包括 [`internal/conversation/message.go:426-430,667-668`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:426:1)、[`internal/conversation/conversation.go:794,1016,1128,1509,1688`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/conversation.go:794:1)。`SendTestWebhook` 直接调用 `deliverSingleWebhook`，不进入 worker queue。

### 8.3 DeliveryTask、队列与配置

`webhook.Manager`：

```text
deliveryQueue chan DeliveryTask
httpClient    *http.Client
workers       int
closed        bool
closedMu      sync.RWMutex
wg            sync.WaitGroup
```

`DeliveryTask` 只含 `Event`、`Payload any`、可选 `WebhookID`，没有 task ID、attempt、created_at 或 idempotency key。

配置 [`config.toml:133-139`](vscode://file/D:/codes/dev_proj/libredesk/config.toml:133:1)：workers=5、queue_size=10000、HTTP timeout=15s。`New` 还设置 3s Dial、TLS handshake、ResponseHeader timeout，并通过项目 SSRF（Server-Side Request Forgery，服务端请求伪造）Transport 控制出站连接；[`cmd/init.go:1138`](vscode://file/D:/codes/dev_proj/libredesk/cmd/init.go:1138:1) 注入这些配置。

Webhook 配置通过 prepared SQL 从 DB 获取；delivery task 和 delivery result 没有对应持久表。

### 8.4 投递状态为何不落数据库

Webhook delivery 没有持久状态机。内存态只有：

```text
created in caller
  → queued
      ├─ worker handled → success log / failure log
      └─ shutdown or process crash → 无持久记录
  └─ queue full / manager closed → drop or return silently
```

关键不变量：

1. `WebhookID <= 0` 不能被当作 targeted delivery，否则会退化成 fan-out；`TriggerWebhook` 明确拒绝。
2. secret 非空时，payload 要带 `X-Libredesk-Signature: sha256=...`；由 `generateSignature` 保证。
3. 只有 2xx 被记为 success。
4. `closedMu.RLock` 覆盖 closed 检查与 channel send，`Close` 写锁覆盖 close，避免普通 Producer 与 close 并发导致 send-on-closed panic。

### 8.5 满队列、失败与停机

#### Enqueue 与背压

`TriggerEvent`/`TriggerWebhook` 用 `select { case queue <- task: default: ... }`，queue 满时立即 drop，仅记 Warn，不阻塞业务调用方，也不返回 error。

#### 关键代码：Webhook 选择非阻塞入队

```go
select {
case m.deliveryQueue <- task:
default:
    m.lo.Warn("webhook delivery queue is full, dropping webhook delivery")
}
```

**这段代码解决什么问题：** 第三方 HTTP 变慢时，Webhook 不能反向卡住 Conversation / Message 的主业务 goroutine。

**为什么这样写：** `select + default` 让入队成为非阻塞操作，过载时立刻执行显式丢弃策略。

**如果没有这段机制会怎样：** 普通阻塞 send 会把 Webhook 消费速度传导为主请求延迟。

**当前工程代价：** 满队列事件没有持久 delivery record，也没有自动重放，可靠性是尽力而为而非至少一次。

【代码分析】这里没有把 backpressure 传播给 Producer；系统选择保护同步业务请求延迟，以丢 Webhook 事件为过载代价。

#### Worker 与顺序

5 个 worker 竞争同一 channel；单个 task fan-out 到多个 Webhook 时，`deliverWebhook` 在该 worker 内按查询结果串行调用各 endpoint。

【代码分析】channel 的 dequeue 有先后，但不同 worker 的 HTTP 完成无顺序保证；同一 Webhook 收到相邻业务事件时也可能乱序。源码没有 per-webhook serialization。

#### 外部 I/O、重试与幂等

HTTP transport error、non-2xx、marshal/read errors 都只记录并 return。在当前 Webhook 投递链及其直接依赖中，未发现自动 Retry（重试）、Backoff（退避）、Requeue（重新入队）、Delivery Attempt（投递尝试记录）或 Dead-letter Table（死信表）。请求中也没有项目生成的 Delivery ID；timestamp 在实际发送时生成。

因此准确表述是：

> 在当前 Webhook 投递链及其直接依赖中，未发现自动重试、退避、持久队列、死信或投递级幂等机制。

这不等同于断言下游服务不能自行幂等。

`http.NewRequest` 没有绑定 worker ctx；正在执行的请求只受 `http.Client.Timeout` 和 Transport timeout 控制，根 ctx 取消不会直接 cancel 该 request。

#### Shutdown

`Close` 置 closed、关闭 queue、等待 worker `wg`；但 main 是在根 ctx 已取消后再调用 `Close`。worker 的 `select` 同时监听 `ctx.Done()` 和 queue。

【代码分析】ctx 已 ready 时，worker 可以直接退出而不 drain（排空）尚未处理的 buffered tasks；`Close` 的“等待 worker”不等于“保证排空 queue”。正在 HTTP I/O 的 worker 最长还可能受 15s client timeout 约束后才返回。

### 8.6 尽力而为语义的收益与代价

业务调用点不接收 delivery error；queue 满时明确日志写着 dropping。HTTP 具备总 timeout、连接阶段 timeout、HMAC signature 和 SSRF 控制。

【代码分析】这是 best-effort（尽力而为）事件通知：隔离业务延迟和外部 endpoint 故障，可靠性让位于调用方低耦合与进程保护。

【合理推断】项目可能把 Webhook 定位为辅助集成而非财务级事件总线；源码没有产品 SLA 文档直接证明。

### 面试表达

> Webhook 走有界内存队列，满时丢弃且没有持久重放，换来较低实现成本和对主业务的弱耦合；因此应准确称为尽力而为，而不是可靠消息队列。

## 9. 跨链路比较：队列、调度、背压与停机

| 维度 | Outgoing Message | SLA | Webhook |
|---|---|---|---|
| 任务产生 | HTTP/AI/Automation 同步写 DB | 业务操作写 applied SLA / schedule | 业务方法同步调用 Trigger |
| Queue 真相 | DB pending + buffered channel | DB 表 + Ticker，无 worker channel | buffered channel |
| 容量 | DB 未设任务容量；channel 5000 | 查询无 `LIMIT`；表无容量 | 10000 |
| 满时 | scanner 阻塞；HTTP 已完成落库 | 不适用 channel 满；DB/内存结果集可能增长 | 立即 drop |
| worker | 10，配置值在 `main` 中以 `MustDuration` 读取后用于整数 range | 2 evaluation loops + 1 sender loop | 5 |
| 同 key 串行 | 无 | 每 loop 内串行，但多实例不串行；deadline 重算有行锁 | 无 |
| 持久性 | pending row 持久 | applied/event/schedule 持久 | task 不持久 |
| 自动 retry | 外发失败改 failed，不自动重试 | DB error/未 processed 可被下一 tick 再见；发送后失败语义不完整 | 未找到 |
| 人工 retry | failed message 有受权 API | 无通用人工 retry API 证据 | 无 delivery record 可重试 |
| 多实例领取 | 无 | notification/evaluation scan 无；部分数据更新有约束/行锁 | 无共享任务 |
| Shutdown drain | 不保证；scanner 未 join | evaluation 两 loop 被 join；notification loop 未 join | 不保证 buffered task drain |

[`cmd/main.go:228`](vscode://file/D:/codes/dev_proj/libredesk/cmd/main.go:228:1) 使用 `ko.MustDuration` 读取 `message.*_queue_workers`，而 config 是整数 10；`conversation.Run` 参数也声明为 `time.Duration` 并用于 `for range outgoingQWorkers`。当前代码编译依赖 Go 1.25（`go.mod`），整数底层类型可 range。这里是类型建模不准确，不应直接描述成运行错误。

【设计建议】将 worker count 保持为 `int`，让配置校验能明确拒绝 0/负数或异常大值，减少 duration 单位语义混入数量配置。

---

### 9.1 顺序、失败、重试与幂等边界

### 顺序保证

- Message pending SQL 无 `ORDER BY`，多 worker，无 per-conversation lock：没有源码证据保证同 Conversation FIFO。
- Webhook 多 worker，无 per-webhook lock：没有源码证据保证 endpoint 事件顺序。
- AI Agent 是明显对照：`inflight/pending` map 按 Conversation ID 保证同进程一次只跑一个 response；运行中再来事件会合并为一次 requeue。该保证仍非跨实例。
- AI embedding 通过代际门（Generation Gate）保证旧 edit job 不覆盖新 edit job，是“允许并行计算、提交时拒绝过期结果”的另一种顺序控制。

### 背压策略

- 阻塞型：Message scanner → outgoing channel；Automation 的小时 TimeTrigger send。
- 丢弃型：Webhook、Automation 业务事件、AI FAQ mining。
- 错误返回型：Conversation incoming、Notification Service；但上游是否传播要继续看调用者，Dispatcher 只记录 Notification error。
- 降级型：AI Agent response queue 满时启动人工 handoff goroutine，而不是静默 drop。

【代码分析】同一个项目按业务重要性选择了不同过载策略（Overload Policy）。面试时不能只说“channel 满了会阻塞”：必须指出每个 send 是否有 `default`、error 是否被上游处理、是否有 durable state。

### 可靠性机制边界

| 机制 | 找到的实际实现 | 不能扩大解释的边界 |
|---|---|---|
| Retry | Message failed 的人工 retry；AI provider 自身对 429/5xx/network 做有限指数 backoff；周期 DB scan 会再看到未完成行 | AI provider retry 不能外推为 Message/Webhook retry |
| Idempotency | SLA pending partial unique index；部分条件 UPDATE；AI Agent 同进程 in-flight；incoming email 有 source-id 检查路径 | 不等于外部发送 exactly-once（恰好一次） |
| Dedup | incoming source ID、FAQ、AI generation 等局部机制 | outgoing source_id 非唯一；Webhook task 无 delivery ID |
| Panic recovery | AI Agent response/mining、Importer job、widget WS forwarder 有局部 recover | Message sender、Webhook worker、SLA loops 当前源码未显示 |
| Persistent queue | Message pending 业务行；SLA schedule 表 | Automation/Webhook/Notification/AI Agent task channel 不持久 |
| Dead letter | 当前源码未显示足够源码证据 | “没有找到”不等于仓库外部设施不存在 |
| Metrics/Trace | 有业务报表 metric、pprof trace、结构化日志 | 在 worker/queue 相关代码和配置中未找到 Prometheus/OpenTelemetry queue depth/drop/retry 指标；不能据此断言部署侧无采集 |

### Shutdown 逐步行为

```text
SIGINT/SIGTERM
  → root ctx canceled
  → main wait returns
  → close agent/livechat WS
  → HTTP ShutdownWithContext(30s)
  → 各 Manager Close（固定顺序）
  → DB.Close / Redis.Close
```

主要 worker 都监听 ctx；多个 Manager 还关闭 channel 并 `wg.Wait`。但根 ctx 先取消，worker select 可以选择退出而不是 drain channel。

需要特别区分：

1. **等待正在执行**：Webhook/Message worker 若已经进入不接受 ctx 的外部函数，只能等函数自行返回；Webhook HTTP 有 timeout，Message 的 Inbox.Send 具体 timeout 由通道实现决定。
2. **尚未执行**：纯内存队列不保证 drain；Message 未执行任务仍有 pending DB row，进程重启可再次扫描；Webhook/Notification/Automation task 会丢失。
3. **producer join**：`conversation.Run` 本身由 `cmd/main.go` 启动但没有加入 `conversation.wg`。其阻塞 channel send 不监听 ctx，而 `Close` 会关闭该 channel。

【代码分析】当 outgoing queue 满、scanner 阻塞在 send、根 ctx 取消使 workers 退出，随后 `conversation.Close` 关闭 queue，scanner goroutine 可能发生 send-on-closed panic。是否在真实停机时触发取决于调度与积压，必须用 G/H 的最小实验确认。

【代码分析】`autoassigner.Close` 持有 `closedMu` 后 `wg.Wait`；`Run` 的 ticker 分支也要获取同一 mutex。若 Close 先持锁、Run 随后选中 ticker 分支，Run 等锁、Close 等 Run Done，存在调度相关死锁窗口。根 ctx 已取消会降低但不消除 select 选择 ticker 的可能。应写专门并发测试确认。

SLA `Close` 只等待两个 evaluation goroutine；`SendNotifications` 是 main 直接启动且未计入 `sla.wg`。Notification loop 在工作后直接 `<-ticker.C`，该等待不与 ctx 竞争。

【代码分析】main 关闭 Notifier 时，SLA notification goroutine 可能尚未完全退出；后续 Send 会得到 closed error 并被 Dispatcher 记录，但 SLA 仍可能标 processed。需要停机时序实验确认。

---

## 10. 已确认的工程限制与待实验验证

### 当前验证状态

| 实验 | 当前状态 | 能得到的结论 |
|---|---|---|
| Conversation、Automation、SLA 非数据库测试 | 已通过 | 当前可运行用例未发现断言失败 |
| Webhook、Autoassigner 专项测试 | 未覆盖 | 不能由其他包测试推断其队列和停机语义正确 |
| SLA PostgreSQL 集成测试 | 环境未满足，已 `SKIP` | 并发 Apply、Notification、Cancel、Idempotency 仍未验证 |
| Message 双实例、Webhook 顺序、Shutdown 竞态 | 未执行 | 这些仍是源码推导的待验证风险，不是已复现故障 |

### 下一步最小实验

按风险优先级建议只做以下 7 个小实验，不提前做完整 Benchmark：

1. **P0 Shutdown safety**：capacity=1 + blocking Inbox，制造 scanner blocked send；cancel + Close，断言无 panic、在 2s 内返回。
2. **P0 Multi-instance message claim**：两个 Manager 同 DB + recording Inbox，断言一个 UUID 的外发次数。
3. **P0 SLA notification ownership**：两个 sender 同时处理一条 schedule，统计站内/Email enqueue 次数。
4. **P1 Message ordering**：同 Conversation 两条消息，2 workers + 可控延迟 Inbox，记录完成序。
5. **P1 Webhook drain/order**：阻塞 HTTP test server，分别验证 ctx cancel 时完成数和同 endpoint 顺序。
6. **P1 Autoassigner Close deadlock**：用很短 ticker 和循环 cancel/Close（可配 `-race`），每轮设超时；收集发生 hang 的 goroutine stack。
7. **P2 Observability baseline**：在不改逻辑前，采集 queue len/cap、pending DB count、worker active、drop/error logs；验证哪些约束先出现，再决定优化。

建议测试命令形态：

```powershell
go test -race -count=50 ./internal/conversation -run 'TestName'
go test -race -count=50 ./internal/sla -run 'TestName'
go test -race -count=50 ./internal/webhook -run 'TestName'
go test -race -count=100 ./internal/autoassigner -run 'TestName'
```

【设计建议】只有实验复现后再选择修复：

- Message 多实例领取可考虑 atomic claim（原子领取）或短 lease，并为外部重复设计 idempotency key；不应直接跳到“上 Kafka”。
- SLA notification 可用 claim 状态/lease + attempt，或同 transaction 领取批次；仍要定义 crash-after-send 的幂等语义。
- Shutdown 应先停止 Producer 并 join，再 close queue；worker 是 drain 还是 abort 要显式选择。
- 顺序若是业务要求，按 Conversation/Webhook ID 分片或使用 per-key serialization；若不是要求，应在契约中明确 unordered。

---

## 11. 面试表达

> LibreDesk 没有用一种队列解决所有异步任务。Message 先持久化为 pending，再由 scanner 和 Worker Pool 外发，重启后仍可重新发现；Webhook 只进入有界内存队列，满时直接丢弃，属于尽力而为；SLA 则以数据库 deadline 为事实源，由 ticker 周期判断。三者的差异本质上来自业务对持久性、延迟和允许丢失程度的不同要求。

## 本章必须记住的源码锚点

### [`conversation.Manager.Run`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:55:1)
**为什么必须记住：** Message scanner、channel 与 Worker Pool 的总入口。  
**面试关联：** 背压为什么停留在后台 scanner？

### [`get-outgoing-pending-messages`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:697:1)
**为什么必须记住：** 重启后仍可重新发现待发送消息的依据。  
**面试关联：** 持久待办为什么仍不等于恰好一次？

### [`sendOutgoingMessage`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:147:1)
**为什么必须记住：** 慢速外部 I/O、失败分类和状态更新的交汇处。  
**面试关联：** 外部副作用和数据库状态之间有哪些失败窗口？

### [`sla.Manager.Run`](vscode://file/D:/codes/dev_proj/libredesk/internal/sla/sla.go:517:1)
**为什么必须记住：** 数据库 deadline 如何被周期性判断。  
**面试关联：** 为什么 SLA 选择 DB 时间状态而不是只用内存 Timer？

### [`webhook.TriggerEvent`](vscode://file/D:/codes/dev_proj/libredesk/internal/webhook/webhook.go:256:1)
**为什么必须记住：** `select + default` 明确了满队列丢弃策略。  
**面试关联：** 非阻塞入队保护了什么，又牺牲了什么？

### [`webhook.Run`](vscode://file/D:/codes/dev_proj/libredesk/internal/webhook/webhook.go:299:1)
**为什么必须记住：** Webhook Worker 数、停止和排空行为都从这里读。  
**面试关联：** 纯内存任务在进程退出时能保证到什么程度？

## 12. 面试追问

1. Message、Webhook 与 SLA 为什么使用不同的调度机制？
2. channel 满时阻塞、丢弃和降级各适合什么业务语义？
3. 数据库 pending 为什么仍不能自动保证恰好一次发送？
4. 关闭 channel、取消 context 和等待 `WaitGroup` 应如何排序？
5. 多实例下 claim、lease、dedup（去重）各解决哪一类问题？
