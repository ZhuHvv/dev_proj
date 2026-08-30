# LibreDesk Conversation / Message 领域模型与状态机源码学习

## 1. 这个模块在 LibreDesk 中解决什么问题

这一章承接[系统架构与生命周期](01-system-architecture-and-lifecycle.md)，聚焦客服系统的业务主干：客户如何进入 Conversation，会话状态如何变化，Message 如何入站、持久化、异步外发并最终变成 `sent` 或 `failed`。

## 本章核心源码

| 优先级 | 文件 / Symbol | 为什么必须读 |
|---|---|---|
| P0 | [`handleSendMessage` → `cmd/messages.go:177`](vscode://file/D:/codes/dev_proj/libredesk/cmd/messages.go:177:1) | Agent 回复的 HTTP 业务入口 |
| P0 | [`QueueReply` → `internal/conversation/message.go:504`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:504:1) | 把公开回复规范化为 `outgoing/pending` Message |
| P0 | [`InsertMessage` → `internal/conversation/message.go:579`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:579:1) | Message、附件关系与事务边界的核心 |
| P0 | [`Manager.Run` → `internal/conversation/message.go:55`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:55:1) | 把数据库 pending 状态重新发现为运行时任务 |
| P0 | [`sendOutgoingMessage` → `internal/conversation/message.go:147`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:147:1) | 外部投递和 `sent/failed` 状态提交点 |
| P0 | [`conversation_messages` → `schema.sql:302`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:302:1) | Message 的外键、状态、类型和索引基础 |
| P1 | [`update-conversation-status` → `queries.sql:455`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:455:1) | Conversation 状态名称与 snooze 时间如何落库 |

## 2. 一张图看懂整体机制

```text
Email / Widget / Agent / Automation / AI
                  ↓
        Conversation 定位或创建
                  ↓
 Message 写 PostgreSQL，并更新会话摘要
          ↙                    ↘
 incoming 已接收          outgoing = pending
                                 ↓
                     scanner → channel → Worker
                                 ↓
                    Email / LiveChat → sent / failed
```

## 3. 必须先理解的核心概念

- **领域模型（Domain Model）**：用 Conversation、Message、Inbox、Contact 等对象表达客服业务规则，而不只是映射数据库表。
- **状态机（State Machine）**：对象只能在允许的状态之间转换；这里既要看状态名称，也要看 `category` 带来的业务分组。
- **业务不变量（Business Invariant）**：任何执行路径都必须保持的规则，例如公开出站消息必须先持久化为 `pending`。
- **幂等（Idempotency）**：同一业务输入重复执行时，不会产生额外副作用；仅“先查再写”在并发下不等于真正幂等。

## 4. 源码阅读路线

**Agent 公开回复：**

① [`handleSendMessage`](vscode://file/D:/codes/dev_proj/libredesk/cmd/messages.go:177:1)
↓ ② [`QueueReply`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:504:1)
↓ ③ [`InsertMessage`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:579:1)
↓ ④ [`insert-message SQL`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:828:1)
↓ ⑤ [`Run`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:55:1)
↓ ⑥ [`sendOutgoingMessage`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:147:1)
↓ ⑦ [`UpdateMessageStatus`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:416:1)

**Conversation 状态：** [`handleUpdateConversationStatus`](vscode://file/D:/codes/dev_proj/libredesk/cmd/conversation.go:570:1) → [`update-conversation-status SQL`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:455:1)。


## 5. 先建立 Conversation / Message 领域模型


### 模块解决什么业务问题？

【代码分析】Conversation 是“一个联系人经一个 Inbox（收件箱/渠道入口）与客服组织持续交互”的业务聚合索引；Message 是该交互中可持久化、可展示、可投递的事实。Conversation 不仅保存关系，还缓存列表查询和服务流程所需的派生状态：最近消息、最近有效交互、等待起点、首次/最近回复时间、负责人、团队、SLA（Service Level Agreement，服务等级协议）和状态。

Message 同时承担三种语义：

- `incoming`：联系人进入系统的消息，状态通常是 `received`；
- `outgoing`：Agent、AI Assistant 或 System User（系统用户）产生的消息，可为公开回复或私有备注；
- `activity`：状态、分配、标签等业务变化形成的会话时间线记录。

证据：[`internal/conversation/models/models.go:33-59,160-209,306-336`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/models/models.go:33:1)；写入路径见 `message.go:445-575,723-750,794-880`。

### 真实领域对象及职责

| 对象 | Struct / Interface | 业务职责 | 关系的业务含义 |
|---|---|---|---|
| Conversation | `models.Conversation` | 聚合联系人、Inbox、状态、分配、SLA、最近交互等当前视图 | Contact 与 Inbox 决定参与人和投递通道；Status、Assignment、SLA 会改变可见性、处理责任和后续动作 |
| ConversationListItem | `models.ConversationListItem` | Agent 列表页的读模型，并承载授权广播所需的 assigned user/team | 不是独立业务实体，是 Conversation 的查询投影；WebSocket 授权广播依赖它 |
| Message | `models.Message` | 保存消息类型、投递状态、发送者、正文、私密性、source ID、meta 和附件关联 | `conversation_id` 决定归属；sender/type/private/status 共同决定业务语义，不能只看外键 |
| IncomingMessage | `models.IncomingMessage` | Email 适配层到 Conversation 领域层的输入模型，携带 threading（邮件串联）信息 | `InReplyTo`、`References`、plus-addressed UUID 会影响“接入既有 Conversation 还是新建” |
| OutboundMessage | `models.OutboundMessage` | 从持久化 Message 转换出的通道投递模型 | 仅包含投递所需字段；Email threading 字段由发送前补充 |
| Contact/User | `umodels.User` / `ConversationContact` | 联系人是 Conversation 的客户主体；Agent/System/AI Assistant 是消息作者或业务动作 actor | 同一 `users` 表的类型语义影响权限、模板和自动化，但数据库外键本身不区分 Agent/Contact |
| Inbox | `inbox.Inbox` / `imodels.Inbox` | 决定 Email 或 LiveChat 发送实现、启停、地址及 CSAT 配置 | 不是普通查表关系；`inb.Send()` 是出站最终外部副作用边界 |
| Assignment | `assigned_user_id` / `assigned_team_id` | 表达当前处理责任和 Conversation 可见范围 | User 与 Team 可同时有值；换 Team 的业务方法会尝试清除 User，但数据库未声明互斥约束 |
| Status | `status/models.Status` | 名称用于 UI/动作，category 用于 open/waiting/resolved 语义分组 | 默认状态受保护；自定义状态允许存在，因此“名称状态机”与“分类状态机”要分开理解 |
| Participant | `conversation_participants` | 记录曾在 Conversation 发过消息的用户，供参与者展示 | 不等于当前 assignee；由每次消息提交后尽力而为（Best-effort）补充 |
| Manager | `conversation.Manager` | Conversation/Message 聚合服务：DB、Inbox、User、Team、SLA、Automation、WS、Webhook 等编排 | 是应用服务而非纯领域实体；多数业务不变量由方法顺序而非实体方法保护 |
| AIAgentEngine | `conversation.AIAgentEngine` | Assignment、入站、Resolved 时通知 AI Agent 子系统 | AI Assistant 最终仍复用 `QueueReply` 和 Conversation 状态方法，不另建消息模型 |

主要定义：[`internal/conversation/conversation.go:83-123,143-209`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/conversation.go:83:1)；[`internal/conversation/models/models.go:91-148,160-209,269-336,433-539`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/models/models.go:91:1)。

### 数据库关系与真正影响流程的关系

数据库关系：

- `conversations.contact_id → users.id`、`inbox_id → inboxes.id` 为 `ON DELETE CASCADE`；删除联系人或 Inbox 会级联删除 Conversation。
- `conversation_messages.conversation_id → conversations.id` 为 `ON DELETE CASCADE`；删除 Conversation 会级联删除消息。
- `conversation_messages.sender_id → users.id` 为 `ON DELETE CASCADE`。
- `assigned_user_id`、`assigned_team_id` 删除时置空；status/priority 删除受限制。
- Conversation UUID、reference number、Message UUID 唯一；Participant `(conversation_id,user_id)` 唯一。

证据：[`schema.sql:239-324,377-400`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:239:1)。

【代码分析】真正驱动流程的关系：

- Conversation→Inbox：决定 `QueueReply` 的校验、模板与 `inb.Send()` 实现。
- Conversation→Contact：决定公开回复收件人、入站发送者覆盖、Widget 资源授权。
- Conversation→Status：决定自动 reopen、resolved 的 AI/CSAT 动作、closed 的 Widget 回复限制。
- Conversation→Assignment：决定 Agent 可见范围、通知对象、AI Assistant 是否被唤醒。
- Message→Conversation：消息提交后会更新 Conversation 摘要并触发订阅者广播。
- Message→source_id：用于 Email 去重和 threading，但当前数据库没有把它提升为唯一业务键。

### 为什么形成当前设计？

`Manager` 在一个进程内持有 DB、内存 channel、WebSocket Hub 和各领域 Store，并由 [`cmd/main.go:263`](vscode://file/D:/codes/dev_proj/libredesk/cmd/main.go:263:1) 启动后台 worker。持久事实进 PostgreSQL，实时通知和投递任务通过内存组件执行。

【合理推断】这是“模块化单体 + 持久化消息状态 + 进程内异步副作用”的折中：实现路径短，单实例部署简单，列表查询也可直接依赖 Conversation 的冗余摘要字段。源码没有设计文档直接说明取舍，故这不是源码事实。

---

## 6. 核心链路一：Conversation 如何创建并改变状态


### 创建入口和真实调用链

### 链路 1：Agent 主动创建 Email Conversation

`POST /api/v1/conversations`
→ `perm(handleCreateConversation, "conversations:write")`
→ `validateCreateConversationRequest`
→ `user.ResolveContact`
→ `conversation.Manager.CreateConversation`
→ 可选 Team/User assignment
→ `QueueReply` 或 `CreateContactMessage`
→ 返回创建后的 Conversation。

证据：[`cmd/handlers.go:76`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:76:1)；[`cmd/conversation.go:787`](vscode://file/D:/codes/dev_proj/libredesk/cmd/conversation.go:787:1)。

创建前检查：Inbox ID、content、email、first name、email 格式、initiator；Inbox 必须存在、启用且 channel 为 `email`；未知 Conversation custom attribute key 被剔除。联系人复用/同步策略受 `contacts:write` 权限和 `reuse_contact` 影响。

创建写入：`CreateConversation` 把 nil meta/custom attributes 归一为 `{}`，以 `Open` 名称查 status ID，生成 reference number，写 contact/inbox/subject/last-message 元数据并返回 ID/UUID。SQL：[`internal/conversation/queries.sql:7`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:7:1)；方法：`conversation.go:374-418`。

创建后副作用：`CreateConversation` 先查询 `ConversationListItem` 并广播新 Conversation；随后 Handler 才做 assignment 和初始 Message。初始消息失败时调用 `DeleteConversation` 补偿删除，但没有看到对应的“删除 Conversation”广播。

【代码分析】因此 API 的业务创建不是单事务：其他 Agent 可能先收到一个尚无初始消息的 Conversation；若后续失败，DB 会补偿删除，但实时客户端可能短暂保留旧投影，需靠刷新或后续同步纠正。

### 链路 2：Widget 创建 LiveChat Conversation

`POST /api/v1/widget/chat/conversations/init`
→ `widgetAuth` + rate limit
→ 校验消息长度、Inbox/config、会话身份
→ 创建/复用 visitor/contact
→ `checkConversationPermissions`
→ `CreateConversation(max=配置常量, window=时间窗)`
→ `InsertMessage(incoming/received)`
→ `ProcessIncomingMessageHooks(isNew=true)`。

证据：[`cmd/handlers.go:358`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:358:1)；[`cmd/chat.go:178`](vscode://file/D:/codes/dev_proj/libredesk/cmd/chat.go:178:1)。

初始 Message 插入失败时删除刚创建的 Conversation；Hook 失败只记录日志，不回滚消息和 Conversation。

### 链路 3：Email 入站按 threading 查找或创建

IMAP `processEnvelope` 检查 Message-ID 与 blocked email
→ 解析正文、附件、`In-Reply-To`、`References`、plus-addressed UUID
→ `EnqueueIncoming`
→ `IncomingMessageWorker`
→ `ProcessIncomingMessage`
→ `resolveByPlusAddress` 或 `findOrCreateConversation`
→ 无匹配时 `CreateConversation`
→ 上传附件、`InsertMessage`
→ `ProcessIncomingMessageHooks`。

证据：[`internal/inbox/channel/email/imap.go:315`](vscode://file/D:/codes/dev_proj/libredesk/internal/inbox/channel/email/imap.go:315:1)；`message.go:114-129,794-880,886-960,1186-1248`。

### 真实状态集合：名称与 category 两层

默认状态是：

- `Open`，category=`open`
- `Snoozed`，category=`waiting`
- `Resolved`，category=`resolved`
- `Closed`，category=`resolved`

证据：[`schema.sql:1007-1012`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:1007:1)；`status/models/models.go:5-22`。

管理员可以创建自定义状态，名称非空且长度受限，category 只能为 `open`、`waiting`、`resolved`；默认状态不能修改/删除。证据：[`internal/conversation/status/status.go:72`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/status/status.go:72:1)。

`models.StatusReplied = "Replied"` 只在常量定义处出现；当前状态读写链中未发现使用它的业务分支。因此不能把 Replied 当作当前可达状态。

### 由真实操作建立的状态机

```text
新建
  └─ CreateConversation 固定写 Open

任意当前状态
  ├─ Agent HTTP / Automation set-status ──> 任意数据库中存在的状态名
  ├─ Automation snooze ──> Snoozed(snoozed_until = now + duration)
  └─ 客户向既有会话发入站消息 ──> Open

Snoozed 且 snoozed_until <= NOW()
  └─ RunUnsnoozer 批量 SQL ──> Open

Open / 自定义状态 / Snoozed / Closed / Resolved
  └─ AI Assistant resolve 或人工/自动化 set-status ──> Resolved
```

这里的“任意”不是枚举推测，而是 `UpdateConversationStatus` 没有读取旧状态来校验 transition，只检查 snooze duration；SQL 通过目标状态名称查 ID。若目标名称不存在，`status_id` 的 NOT NULL 约束会让更新失败。证据：`conversation.go:955-1074`；`queries.sql:455-465`；[`schema.sql:260-262`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:260:1)。

### 状态转换明细

| From | To | 触发者/入口 | Method / SQL | 数据变化 | 副作用 |
|---|---|---|---|---|---|
| 无 | Open | Agent/Widget/Email 创建 | `CreateConversation` / `insert-conversation` | 新 Conversation、reference number、status ID | 立即广播 new conversation |
| 任意 | 任意已存在状态 | Agent HTTP 或 Automation | `UpdateConversationStatus` / `update-conversation-status` | status；首次进入 resolved category 时填 `resolved_at`；首次 Closed 时填 `closed_at`；Snoozed 设置时间，否则清空 | SLA evaluate、Webhook、activity、WS、Automation、Widget；进入 `Resolved` 名称时通知 AI 并可能排队 CSAT |
| 非 Open | Open | 既有 Conversation 收到客户消息 | `ProcessIncomingMessageHooks` → `ReOpenConversation` | status=Open、清 snooze；若当前 assignee 是 `away_and_reassigning` 则清 user assignee | SLA evaluate、Agent WS、status activity；**未见 status-change Webhook/Automation/Widget broadcast 在此方法内触发** |
| Snoozed 到期 | Open | 定时 goroutine | `RunUnsnoozer` → `unsnooze-all` | 批量 status=Open、清 snooze | 只记受影响行数日志；未见逐会话 activity/WS/Webhook/Automation |

`resolved_at` 和 `closed_at` 用 `COALESCE`，重新打开不会清除；它们更像“首次达到该里程碑时间”，不是“当前正处于该状态”的唯一依据。证据：`queries.sql:459-464,612-632`。

【代码分析】状态变化路径的副作用并不统一：HTTP/Automation 走 `UpdateConversationStatus`，入站 reopen 走 `ReOpenConversation`，定时 unsnooze 直接批量 SQL。业务状态最终一致，但审计、Webhook、Widget 和 Automation 的可见副作用可能不同。

### 当前实现值得验证的状态约束

- 自定义 `resolved` category 状态不会命中 `status == "Resolved"` 的 AI resolved/CSAT 分支，但 SQL 会填 `resolved_at`，SLA 也按 category 评估。是否符合产品语义需产品测试确认。
- `ReOpenConversation` 只广播 Agent 侧 partial update；Widget 是否会通过其他路径及时看到 reopen，需端到端实验。
- unsnoozer 批量更新无逐项广播；前端在不刷新情况下何时感知 Open，需实验。

---

## 7. 核心链路二：Message 如何入站与异步外发


### 外部用户产生 Message

### Widget 既有 Conversation 消息

入口：`POST /api/v1/widget/chat/conversations/{uuid}/message`。

调用链：

`handleChatSendMessage`
→ 非空/最大长度校验
→ `getContactConversation` 校验 session contact 与 Conversation.contact、Inbox 一致
→ `canReply`
→ 构造 `incoming + received + contact + public`
→ `ProcessIncomingLiveChatMessage`
→ 附件上传
→ `InsertMessage`
→ 更新 contact last seen
→ `ProcessIncomingMessageHooks(false)`
→ 再查询 Message 并返回 Widget DTO。

证据：[`cmd/chat.go:517-566,710-736,1293-1310`](vscode://file/D:/codes/dev_proj/libredesk/cmd/chat.go:517:1)；`message.go:979-1002`。

状态限制：只有 `Closed` 被特殊检查，而且是否禁止回复由 LiveChat config 分别针对 visitor/user 决定。Resolved、Snoozed、自定义 waiting/resolved 状态没有在 `canReply` 中直接禁止；若允许写入，Hook 会尝试 reopen 为 Open。

### Email 入站消息

入口和链路见 B.1 链路 3。关键差异：

- 必须有 Message-ID，否则 IMAP 层直接丢弃；blocked email 直接忽略。
- IMAP 层和 `ProcessIncomingMessage` 各做一次 `source_id` 存在性检查。
- plus-addressing 优先决定 Conversation；否则用 `In-Reply-To`/`References` 对既有 Message.source_id 查 Conversation。
- 需要时 ResolveContact；新会话初始状态为 Open。
- 附件先上传，再在 Message 事务内关联；新建会话场景下上传或插入失败会补偿删除 Conversation。
- Message 提交完成后再广播到 LiveChat widget（仅当目标 Inbox 实例是 LiveChat）并执行 reopen/automation/AI/SLA hooks。

### 入站提交后的状态与副作用

`InsertMessage` 的 DB 事务只包含：

1. 写 `conversation_messages`；
2. `LinkMessageMediaTx` 关联附件/inline media；
3. commit。

提交后依次 best-effort：参与者、Conversation last-message/last-interaction 摘要、Agent WebSocket new-message、Message 重新查询、message-created Webhook。证据：`message.go:578-670`。

随后入站 Hook：先设置 `waiting_since=now`；新 Conversation 触发 conversation-created Webhook 和 new-conversation Automation 后返回；既有 Conversation 则尝试 reopen，再执行 incoming-message Automation、AI Agent 唤醒和 next-response SLA event。证据：`message.go:1366-1428`。

### Agent / System / AI 产生 Message

### 人工 Agent 公开回复

入口：`POST /api/v1/conversations/{cuuid}/messages`。

`handleSendMessage`
→ action permission + `enforceConversationAccess`
→ payload decode
→ Inbox 存在且 enabled
→ sender type 校验；“as contact”另查权限；Contact 不可发 private
→ 解析未关联附件
→ `QueueReply`
→ 返回 status=`pending` 的 Message。

`QueueReply` 对 Email 清洗 to/cc/bcc、要求至少一个 to、生成 source ID；渲染模板变量；写 `outgoing + agent + public + pending`。LiveChat 不要求 to。证据：[`cmd/messages.go:176`](vscode://file/D:/codes/dev_proj/libredesk/cmd/messages.go:176:1)；`message.go:503-575`。

### 私有备注

`handleSendMessage(private=true)` → `SendPrivateNote` → `InsertMessage`。

私有备注是 `outgoing + agent + private + sent`，不会进入投递 Worker。Mentions（提及）在 Message 已提交后另行插入；失败只记日志，通知通过 goroutine 异步执行。证据：`message.go:445-475,579-582`。

### Automation / System reply

`conversation.Manager.ApplyAction(ActionReply)` 选择 actor；缺省时使用 System User；只给 Conversation.contact.email 发送，不继承历史 CC；meta 写 `is_automated=true`；随后复用 `QueueReply`。`Message.ShouldEvaluateAutomation` 会阻止 System User 或 `is_automated` Message 再触发 outgoing automation，以避免规则循环。证据：`conversation.go:1404-1478`；`models.go:348-360`。

### AI Assistant reply

AI worker 生成答案后重新读取 Conversation：若 assignee 已变化或 status category 已不可处理，则丢弃本轮回复/状态动作。之后 `postReply` 写 `ai_assistant_id` meta 并复用 `QueueReply`；若模型选择 resolve，先排队回复，再调用 `UpdateConversationStatus(Resolved)`，使 CSAT 在回复之后排队。证据：[`internal/aiagent/worker.go:330-394,418-431`](vscode://file/D:/codes/dev_proj/libredesk/internal/aiagent/worker.go:330:1)。

【代码分析】这项 fresh-read 是“减少 AI 与人工接管冲突”的乐观保护，但不是 compare-and-swap（比较并交换）：读取后到 `QueueReply` 之间仍有竞态窗口。

### 出站 pending → sent/failed

启动关系：[`cmd/main.go:223-230,272-277`](vscode://file/D:/codes/dev_proj/libredesk/cmd/main.go:223:1) 从配置读取 worker 数、扫描间隔，并启动 `conversation.Run`。当前 `config.toml`、`config.sample.toml`、本地 `config.dev.toml` 都是 outgoing/incoming workers=10、queue size=5000、scan interval=50ms；unsnooze interval=5m。

调用链：

`Run`
→ 每个 scan tick 执行 `get-outgoing-pending-messages`
→ 排除当前进程 `sync.Map` 中的 ID
→ 放入内存 `outgoingMessageQueue`
→ `MessageSenderWorker`
→ `sendOutgoingMessage`
→ 获取 Inbox、渲染、加载附件、构造 OutboundMessage
→ Email 补 threading headers
→ `inb.Send`
→ `UpdateMessageStatus(sent/failed)`
→ 成功的人类回复更新 reply timestamps、waiting_since、SLA、WS、outgoing Automation。

证据：`message.go:53-240`；SQL：`queries.sql:697-729,856-860`。

特殊失败语义：

- 一般 `inb.Send` error → 标记 `failed`。
- `livechat.ErrClientNotConnected` 被当作可接受结果，随后标记 `sent`。
- HTTP retry 只允许原发送者对本 Conversation 中自己发出的 `agent + failed` Message 重置为 `pending`。证据：[`cmd/messages.go:141`](vscode://file/D:/codes/dev_proj/libredesk/cmd/messages.go:141:1)。

### Message 数据变化总表

| 场景 | Type | Sender type | Private | 初始 status | 后续 status |
|---|---|---|---:|---|---|
| Widget/Email 客户消息 | incoming | contact | false | received | 当前核心链路未修改 |
| Agent 公开回复 | outgoing | agent | false | pending | sent 或 failed；人工 retry 可回 pending |
| Automation/System 回复 | outgoing | agent（sender ID 为 system actor） | false | pending | sent 或 failed |
| AI Assistant 回复 | outgoing | agent（sender ID 为 assistant user） | false | pending | sent 或 failed |
| 私有备注/activity | outgoing/activity | agent | true/false | sent | 不进入公开出站队列 |

数据库 enum 只允许 `received/sent/failed/pending`，Message type 只允许 schema 中的 message_type；证据：[`schema.sql:6`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:6:1) 和 `conversation_messages` 字段定义。

---

## 8. 两条链共同依赖的业务不变量


### 不变量 1：Message 必须属于真实 Conversation，正文与附件关系要一起提交

**业务规则：**Message 不能脱离 Conversation；消息行与本次附件关联要原子提交。

证据：`InsertMessage` 在同一个 `sqlx.Tx` 中执行 `InsertMessage` 和 `LinkMessageMediaTx`，任一步失败都会 rollback。SQL 的 Conversation CTE 按 ID/UUID 找归属。`message.go:578-624`；`queries.sql:828-849`。

**数据库保证：**是。`conversation_messages.conversation_id NOT NULL REFERENCES conversations(id) ON DELETE CASCADE`，见 [`schema.sql:302-318`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:302:1)。

**若违反：**不存在的 Conversation 会使 insert 无法得到有效非空 conversation_id；附件关联失败则消息事务回滚。

### 不变量 2：公开出站消息先持久化 pending，成功投递后才变 sent

**业务规则：**公开 Agent/System/AI 回复不能绕过 `pending` 持久状态直接视为已投递；私有备注例外，直接 `sent` 且不外发。

证据：`QueueReply` 固定 `outgoing/pending/private=false`；`InsertMessage` 强制 private message 为 sent；Worker SQL 只查 `pending + outgoing + private=false`；`sendOutgoingMessage` 在 `inb.Send` 后更新 sent。[`internal/conversation/message.go:146-197,503-582`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:146:1)；[`internal/conversation/queries.sql:697`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:697:1)。

**数据库保证：**部分保证。enum 限制 status/type 值，但没有 CHECK 保证 `(private=true ⇒ sent)` 或 `(pending ⇒ outgoing/public)`。

**若违反：**错误组合可能永不投递或被错误扫描；当前正规领域方法维持组合，直接 SQL/新调用者可能绕过。

### 不变量 3：Conversation 的客户、Inbox 与 Widget session 必须一致

**业务规则：**Widget 只能读写其 session contact 且属于同一 Inbox 的 Conversation。

证据：`getContactConversation` 同时比较 `conversation.ContactID` 和 `conversation.InboxID`；所有既有 Widget message/media 路径先调用它。[`cmd/chat.go:710-736,540-546,586-593`](vscode://file/D:/codes/dev_proj/libredesk/cmd/chat.go:710:1)。

**数据库保证：**外键只保证 ID 存在，不保证请求 session 的资源所有权；该规则只在应用层。

**若违反：**返回 PermissionError，阻止跨联系人/跨 Inbox 访问。

### 不变量 4：Agent 操作既要有 action permission，也要有 Conversation 资源访问权

**业务规则：**拥有 `messages:write`/`conversations:update_*` 动作权限，不代表能操作所有 Conversation。

证据：路由用 `perm(...)`；Handler 再调用 `enforceConversationAccess`，读取 Conversation 后由 `authz.EnforceConversationAccess` 判断 assignment/team 等资源范围。[`cmd/handlers.go:58`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:58:1)；[`cmd/conversation.go:720`](vscode://file/D:/codes/dev_proj/libredesk/cmd/conversation.go:720:1)；[`cmd/messages.go:185`](vscode://file/D:/codes/dev_proj/libredesk/cmd/messages.go:185:1)。

**数据库保证：**否，数据库没有行级资源授权约束。

**若违反：**应用返回 PermissionError；绕过 Handler 的内部调用必须自行保证 actor/资源边界。

### 不变量 5：同一 Participant 只记录一次，但 Participant 不等于 Assignee

**业务规则：**发送过消息的用户可成为参与者，同一 Conversation/User 不重复；当前负责人由 assignment 字段独立表达。

证据：Message commit 后 `addConversationParticipant`；SQL `ON CONFLICT DO NOTHING`。`message.go:626-627`；`conversation.go:1792-1823`；`queries.sql:508-512`。

**数据库保证：**是。唯一索引 `(conversation_id,user_id)`，见 [`schema.sql:377-386`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:377:1)。

**若违反：**正规插入会去重；参与者补写失败不会回滚已提交 Message，因此可能短暂或永久缺参与者记录。

### 不变量 6：自动认领同一时刻只能从预期 Team 的 unassigned 状态成功

**业务规则：**Autoassigner（自动分配器）认领时，Conversation 必须仍无 user assignee 且 team 未变化。

证据：`ClaimUnassignedConversation` 检查 RowsAffected；0 行返回 `ErrConversationAlreadyAssigned`。Autoassigner 遇到该错误停止本 Conversation 后续候选。`conversation.go:761-785`；`autoassigner.go:230-251`。

**数据库保证：**由单条条件 UPDATE 实现：`WHERE uuid=$1 AND assigned_user_id IS NULL AND assigned_team_id=$3`，见 `queries.sql:436-440`；没有额外唯一约束。

**若违反：**竞争失败者得到业务错误，不覆盖赢家。

### 不变量 7：换 Team 时应清除旧 User assignee，但它不是数据库不变量

**业务规则：**当 Team 真正变化时，旧 assigned user 应被清除；创建流程也明确“先 Team、再 User”。

证据：`UpdateConversationTeamAssignee` 先写 Team，若 team ID 变化再调用 `RemoveConversationAssignee(user)`。[`cmd/conversation.go:860`](vscode://file/D:/codes/dev_proj/libredesk/cmd/conversation.go:860:1)；`conversation.go:840-879`。

**数据库保证：**否。两个字段可同时存在；更新 Team 与清 User 是两条独立 SQL、无共同事务。User assignment 也不会验证其属于 assigned team。

**若违反：**并发或中间失败可能留下“新 Team + 旧 User”；权限广播、通知、SLA 可能看到不同阶段的组合。

### 不变量 8：Email source ID 用作去重/threading，但当前不是强唯一键

**业务规则：**同一入站 Message-ID 应被忽略；reply references 应定位到已有 Conversation。

证据：IMAP `MessageExists`；`ProcessIncomingMessage` 再查一次；`findOrCreateConversation` 用 source IDs 查 Conversation。`imap.go:323-346`；`message.go:794-802,1194-1248`。

**数据库保证：**否。`source_id` 只有普通索引 `index_conversation_messages_on_source_id`，未见 unique；见 [`schema.sql:314,322`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:314:1)。

**若违反：**并发 check-then-insert 可能写入重复入站消息，或不同消息共享 source ID 后 threading 选择任一匹配行；是否可复现需实验。

### 不变量 9：Snoozed 必须带正 duration；离开 Snoozed 要清 snoozed_until

**业务规则：**显式进入 Snoozed 必须提供可解析且大于 0 的 duration；其他 status 更新清 snooze time。

证据：Handler 做非空/parse，Manager 再做非空、parse、`duration > 0`；SQL CASE 只为 Snoozed 保存时间。[`cmd/conversation.go:586`](vscode://file/D:/codes/dev_proj/libredesk/cmd/conversation.go:586:1)；`conversation.go:955-979`；`queries.sql:455-465`。

**数据库保证：**否。数据库没有 CHECK 绑定 status 与 snoozed_until；直接 SQL 可破坏。

**若违反：**正规 API 返回 InputError；DB 层不会独立阻止不一致组合。

---

## 9. 完整机制之后再看异常与并发边界


### 两个请求同时修改同一 Conversation

普通 status、priority、user/team assignment 是“先读旧值 → 无版本条件 UPDATE → 再副作用”，没有 `version` 字段或旧值条件。最后提交的 UPDATE 决定最终字段值；两条请求都可能基于相同 previous snapshot 触发 activity/Webhook/Automation。

【合理推断】状态事件顺序与最终状态可能不一致；两个 team/user assignment 交叉时，分步清理 assignee 可能覆盖或清除另一请求的结果。

**已确认的例外：**Autoassigner 的 `ClaimUnassignedConversation` 使用条件 UPDATE，能对“仍未分配且 team 未变”这一认领条件做竞争保护。

### 两个 Agent 同时回复

`handleSendMessage` 没有检查 Conversation 状态或排他 reply lock。两次请求可各自插入 pending Message；队列默认有 10 个 outgoing workers，pending 查询没有 `ORDER BY`。

【代码分析】两个回复都可能被投递，且代码没有显式保证按 Message ID/created_at 顺序发送。不能仅凭代码断言外部渠道一定乱序；这是需要注入延迟的实验问题。

### Message 创建部分失败

Message row + media link 事务失败会一起回滚。新建 Conversation 的初始 Message 失败时，Handler/入站流程尝试删除新 Conversation。

Message commit 之后，Participant、Conversation 摘要、WS、refetch、Webhook 不在事务内。其中 `UpdateConversationLastMessage` 返回值被忽略；refetch 失败仍用已有对象触发 Webhook；Webhook 只是非阻塞入内存队列，队列满直接丢弃。

【合理推断】数据库已有 Message，但 Conversation 列表摘要未更新、参与者缺失或实时/外部事件缺失。读取 Message 明细仍可看到持久事实。

### 状态更新和副作用部分成功

`UpdateConversationStatus` 先提交 status SQL，后做 SLA、fetch、Webhook enqueue、activity insert、CSAT QueueReply、WS、Automation、Widget broadcast。部分步骤只记日志；activity 失败则方法返回错误，但 status 已改变，无法回滚。

【代码分析】调用者收到错误不等于状态没变；盲目重试可能重复非幂等副作用。相同非-Snoozed status 的 early return 会抑制部分重复，但无法覆盖“首次调用已改状态、activity 失败”的所有副作用恢复。

### 出站重复执行与丢失窗口

scanner 通过当前 `Manager` 的 `sync.Map` 排除本进程处理中 ID；SQL 没有 claim 字段、lease（租约）、`FOR UPDATE SKIP LOCKED` 或 status 的原子 pending→processing 转换。

【合理推断】多实例可同时扫描同一 pending Message；进程在外部发送成功后、写 sent 前崩溃，重启后会再次发送。`UpdateMessageStatus` 错误在 `sendOutgoingMessage` 中未向上处理，也可能让已发送消息保持 pending。

Webhook 更弱：纯内存有界队列，queue full 时直接 drop；delivery HTTP 失败只日志，不重试、不持久化。证据：[`internal/webhook/webhook.go:255-360,402-430`](vscode://file/D:/codes/dev_proj/libredesk/internal/webhook/webhook.go:255:1)。

### 入站重复执行

去重是两层“查询后决定”，但 insert SQL 不携带 `ON CONFLICT(source_id)`，schema 无 source_id unique。

【合理推断】两个 Worker/实例并发处理相同 Message-ID 时，两次查询都可能未命中并各自插入。需要真实 PostgreSQL 并发实验确认出现概率和最终行数。

### 资源生命周期

`conversation.Manager.Close` 设置 closed、关闭 incoming/outgoing channel 并等待 Worker WaitGroup；`EnqueueIncoming` 持 closed lock，关闭后返回错误，满队列非阻塞失败。`Run` 本身由 context 停止；scanner 向 outgoing channel 的发送不是带 context 的 select。证据：`message.go:53-143,1018-1032`。

【合理推断】关闭时若 scanner 正阻塞向已满 outgoing queue 发送，与 Close 的 channel close/worker 停止顺序可能产生等待或 send-on-closed-channel 风险；需要受控 lifecycle 测试，不能仅凭静态阅读断言必现。

### 当前实现形成原因与边界

Conversation 表缓存 last-message/interaction 和 SLA deadline 字段；Message 先落 DB 再由 worker 发送；WS/Webhook/Automation 均在核心写入之后调用。这直接支持快速列表读取、HTTP 快速返回和异步通道发送。

【合理推断】作者偏向“核心数据优先持久化、派生效果尽力完成”，而非跨组件强一致。源码没有直接声明该设计目标。

【设计建议】若要求多实例和可恢复副作用，可考虑：

- 出站消息增加 processing/lease/attempt 字段，以条件 UPDATE 或 `FOR UPDATE SKIP LOCKED` claim；外部通道支持时携带幂等键。
- Message + Conversation summary + Outbox（事务外盒）事件同事务提交，由独立消费者负责 WS/Webhook/Automation。
- 入站 `source_id` 使用符合渠道语义的唯一键（可能需 `(inbox_id, source_id)`），insert 用冲突处理而非 check-then-insert。
- Conversation 写入增加 version 或目标旧状态条件，对状态/分配使用 CAS，并把 transition policy 集中化。

这些都是替代设计，不是当前实现。

---

## 10. 已确认的工程限制与待实验验证


每个实验只验证一个潜在约束，不先做完整 Benchmark（基准测试）。

### 入站 Message-ID 并发去重

准备一条固定 `IncomingMessage.SourceID` 和真实 Inbox/Contact，使用 barrier 同时启动 2 个 goroutine 调用 `ProcessIncomingMessage`；查询：

```sql
SELECT source_id, COUNT(*)
FROM conversation_messages
WHERE source_id = $1
GROUP BY source_id;
```

验收：若 count>1，证明应用层 check-then-insert 无法提供强幂等；若本次为 1，也只能说明此次未触发竞态，应重复小批次而非直接宣称安全。

### 双实例出站重复投递窗口

使用可记录 request ID 的 fake Inbox transport，启动两个 `Manager.Run` 共享数据库，各 1 worker；插入一条 pending Message，让第一次 send 阻塞在“外部已记录但 status 未更新”的 barrier，再允许第二实例 scan。

验收：记录同一 Message UUID 的 Send 调用次数和最终 DB status。该实验验证多实例 claim，而非通道性能。

### 两个 Agent 并发回复的顺序

对同一 Conversation 同时 `QueueReply` 两条带序号内容的 Message；fake transport 对第一条增加延迟，workers=2。记录 DB created_at/ID 顺序与 transport 实际完成顺序。

验收：只回答“代码是否保证投递顺序”，不做吞吐 Benchmark。

### Team/User assignment 竞态

初始为 Team A + User A。barrier 同时执行 `UpdateConversationTeamAssignee(Team B)` 与 `UpdateConversationUserAssignee(User C)`，重复有限次数，读取最终 `(assigned_team_id, assigned_user_id)` 及 activity 顺序。

验收：检查是否出现 Team B + nil、Team B + User C、或与 activity/WS 不一致的组合；结合业务期望判断，而不是预设两字段必须互斥。

### Message commit 后摘要失败

用 mock/fault injection 让 `UpdateConversationLastMessage` 失败，但保持 Message transaction 成功；随后分别查询 messages 明细与 conversations.last_message。

验收：验证 API/WS/Webhook 的实际返回与 DB 派生字段是否分叉，并决定是否需要修复任务/Outbox。

### 状态路径副作用一致性

分别通过：

1. `UpdateConversationStatus(Snoozed→Open)`；
2. 客户入站触发 `ReOpenConversation`；
3. 到期 `unsnooze-all`；

记录 DB status、activity、Webhook fake receiver、Agent WS、Widget WS、Automation invocation。

验收：得到一张真实路径/副作用矩阵，确认差异是否是产品意图。

### 当前验证状态

| 实验 | 当前状态 | 能得到的结论 |
|---|---|---|
| Conversation / models / AI Agent 非数据库测试 | 已通过 | 当前可运行的纯逻辑用例未发现断言失败 |
| Autoassigner、status、priority 专项测试 | 未覆盖 | 这些包没有对应测试用例，不能由其他包结果代替 |
| PostgreSQL 并发与双实例 Message 投递 | 未执行 | 本章的 claim、重复投递和顺序风险仍属于待验证问题 |

---

## 11. 面试表达

> LibreDesk 的公开回复不会在 HTTP Handler 中同步等待 Email 或 LiveChat。`QueueReply` 先通过 `InsertMessage` 把 outgoing Message 以 `pending` 持久化，HTTP 因而可以在外部 I/O 前结束。后台 scanner 再发现 pending 数据，写入进程内 channel，由 Worker 调用 Inbox 通道发送，并把状态更新为 `sent` 或 `failed`。数据库让重启后仍能重新发现未完成消息，但当前查询没有跨实例 claim，因此不能直接宣称恰好一次投递。

## 本章必须记住的源码锚点

### [`QueueReply`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:504:1)
**为什么必须记住：** Agent、System 与 AI 公开回复进入统一 Message 模型的入口。  
**面试关联：** 为什么公开回复先写成 `pending`？

### [`InsertMessage`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:579:1)
**为什么必须记住：** Message 与附件关系的事务核心。  
**面试关联：** 哪些数据共同回滚，哪些副作用在事务外？

### [`Manager.Run`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:55:1)
**为什么必须记住：** 把 PostgreSQL 中的持久待办转换为进程内 Worker 任务。  
**面试关联：** 为什么数据库和 channel 同时存在？

### [`sendOutgoingMessage`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:147:1)
**为什么必须记住：** `Inbox.Send` 与 `sent/failed` 状态的提交点。  
**面试关联：** 外部成功、数据库更新失败为什么会形成重复窗口？

### [`UpdateConversationStatus`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/conversation.go:956:1)
**为什么必须记住：** 状态名称、snooze、SLA 与后续副作用的交汇处。  
**面试关联：** 当前状态转换由哪里校验？

### [`conversation_messages`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:302:1)
**为什么必须记住：** Message 归属、类型与投递状态的数据库底座。  
**面试关联：** 哪些不变量由外键和枚举保证，哪些仍依赖 Go？

## 12. 面试追问

1. `InsertMessage` 的事务边界保证了什么，又覆盖不了什么？
2. Conversation 状态名称和 `category` 为什么要分开理解？
3. 为什么 Email `source_id` 的“先查再写”不等于并发幂等？
4. 外部发送成功但状态更新失败时，下一轮扫描可能发生什么？
5. 多实例部署时应怎样为 pending Message 增加 claim / lease？
