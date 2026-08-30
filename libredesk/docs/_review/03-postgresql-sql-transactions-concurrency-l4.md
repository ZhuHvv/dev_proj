# LibreDesk PostgreSQL、SQL、事务与并发一致性源码学习

## 1. 这个模块在 LibreDesk 中解决什么问题

[上一章](02-domain-conversation-message-state-machine-l4.md)已经建立 Conversation 与 Message 的业务对象、状态和不变量；本章不重复业务流程，而是沿同一条链下沉到 PostgreSQL，区分哪些规则由 Schema、Constraint（约束）、Transaction（事务）和原子 SQL 保证，哪些仍依赖 Go 代码按正确顺序调用。

## 本章核心源码

| 优先级 | 文件 / Symbol | 为什么必须读 |
|---|---|---|
| P0 | [`InsertMessage` → `internal/conversation/message.go:579`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:579:1) | Message 与 Media 的事务边界 |
| P0 | [`insert-message` → `queries.sql:828`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:828:1) | Message 写入和返回字段的真实 SQL |
| P0 | [`claim-unassigned-conversation` → `queries.sql:436`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:436:1) | 条件 UPDATE 如何实现并发认领 |
| P0 | [`apply-sla` → `internal/sla/queries.sql:39`](vscode://file/D:/codes/dev_proj/libredesk/internal/sla/queries.sql:39:1) | 公共表表达式（CTE）内完成旧 SLA 结算与新 SLA 建立 |
| P0 | [`conversation_messages` → `schema.sql:302`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:302:1) | 消息关系、状态与索引的数据库底座 |
| P0 | [`applied_slas` → `schema.sql:555`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:555:1) | pending SLA 的部分唯一约束 |
| P1 | [`ScanSQLFile` → `internal/dbutil/scanner.go:13`](vscode://file/D:/codes/dev_proj/libredesk/internal/dbutil/scanner.go:13:1) | SQL 嵌入、解析与预编译语句（Prepared Statement）绑定方式 |

## 2. 一张图看懂整体机制

```text
HTTP / Worker
    ↓
Manager 选择 prepared query 或开启 Transaction
    ↓
Conversation / Message / Media / SLA 等表
    ↓
Constraint 保证结构合法，原子 SQL 处理局部并发
    ↓
提交后再触发 WebSocket、Webhook、Automation 等副作用
```

## 3. 必须先理解的核心概念

- **事务（Transaction）**：一组数据库操作要么全部提交、要么全部回滚；它只能覆盖同一数据库事务中的操作，不能自动覆盖外部邮件或 WebSocket。
- **隔离级别（Isolation Level）**：并发事务互相可见的规则；未显式指定时要以 PostgreSQL 和驱动默认行为理解。
- **约束（Constraint）**：由数据库强制执行的数据规则，例如外键、唯一约束与检查约束。
- **原子领取（Atomic Claim）**：用一条带条件的更新语句完成“检查仍未领取并写入领取者”，避免两个请求都基于旧状态成功。
- **读已提交（Read Committed）**：PostgreSQL 默认隔离级别；并发 UPDATE 等待前一事务后，会在最新已提交行版本上重新检查 `WHERE` 条件。
- **部分索引（Partial Index）**：只为满足谓词的行建立索引；`applied_slas` 用它约束每个 Conversation 至多一条 pending SLA。
- **复合索引（Composite Index）**：由多列按顺序组成的索引；是否匹配查询取决于 `WHERE`、`JOIN` 和 `ORDER BY`，仍需 `EXPLAIN` 确认实际计划。
- **更新或插入（Upsert）**：冲突时更新、否则插入；LibreDesk 用 `ON CONFLICT DO UPDATE` 维护每用户每会话唯一的 last-seen 记录。
- **受影响行数（RowsAffected）**：数据库返回本次写操作实际修改的行数；Autoassign 用 0 行识别认领失败，而不是把无异常当作成功。
- **横向子查询（LATERAL）**：允许右侧子查询引用左侧当前行；Conversation 列表用它为每个会话选择最近的 SLA 数据。

## 4. 源码阅读路线

**Message 持久化路线：** [`QueueReply`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:504:1) → [`InsertMessage`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:579:1) → [`insert-message`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:828:1) → `LinkMessageMediaTx` → `Commit` → 事务外摘要与广播。

**Autoassign 并发认领路线：** `assignConversations` → [`claim-unassigned-conversation`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:436:1) → 条件更新（Conditional Update）→ `RowsAffected` → `ErrConversationAlreadyAssigned`。

**SLA 唯一约束路线：** `ApplySLA` → [`apply-sla`](vscode://file/D:/codes/dev_proj/libredesk/internal/sla/queries.sql:39:1) → [`applied_slas`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:555:1) → pending 部分唯一索引。

**待发送查询与索引路线：** [`get-outgoing-pending-messages`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:697:1) → [`conversation_messages`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:302:1) → `status` 索引匹配分析 → `EXPLAIN (ANALYZE, BUFFERS)` 实验。


## 5. 数据访问层如何组织

### 库、连接和版本

[`go.mod`](vscode://file/D:/codes/dev_proj/libredesk/go.mod:19:1) 固定 `github.com/jmoiron/sqlx v1.4.0`，驱动为 [`github.com/lib/pq v1.10.9`](vscode://file/D:/codes/dev_proj/libredesk/go.mod:32:1)。[`cmd.initDB`](vscode://file/D:/codes/dev_proj/libredesk/cmd/init.go:950:1) 拼接 DSN，调用 `sqlx.Connect("postgres", dsn)`，再设置 `max_open`、`max_idle`、`max_lifetime`。本地三份配置的值均为 30、30、300s；[`docker-compose.yml`](vscode://file/D:/codes/dev_proj/libredesk/docker-compose.yml:24:1) 使用 PostgreSQL 17。

【代码分析】`sqlx` 是 `database/sql` 的增强层，不是 ORM。连接池由所有 Handler、Worker 和 Manager 共享；配置 30 只是并发连接上限，不足以单独证明瓶颈。

### SQL 如何组织和加载

每个模块把 `queries.sql` 通过 `//go:embed` 嵌入二进制。例如 Conversation 在 [`conversation.go`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/conversation.go:50:1) 声明 `embed.FS`；`Manager.New` 调用 [`dbutil.ScanSQLFile`](vscode://file/D:/codes/dev_proj/libredesk/internal/dbutil/scanner.go:13:1)：

```text
fs.ReadFile("queries.sql")
  -> goyesql.ParseBytes
  -> goyesql/sqlx.ScanToStruct
  -> 根据 `query:"name"` 写入 *sqlx.Stmt 或 string 字段
```

静态 SQL 预编译为 `*sqlx.Stmt`；需要动态拼过滤、排序、分页的 `get-conversations`、`get-messages` 保留为 `string`。Conversation 的绑定清单见 [`queries`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/conversation.go:298:1)。

### Query 如何调用；抽象层次

模块普遍以 `Manager` 持有 `*sqlx.DB` 和 query struct，直接 `Stmt.Get/Select/Exec/QueryRow`。没有统一的通用 Repository；Conversation 通过 `inboxStore`、`userStore`、`teamStore`、`mediaStore`、`slaStore` 等领域窄接口依赖其他 Manager。

【代码分析】这是“模块 Manager + SQL Store”而不是标准仓储模式（Repository Pattern）。优点是调用链短；代价是事务跨模块传递只能靠显式 `*sqlx.Tx` 方法，未形成统一工作单元（Unit of Work）。

### Transaction 如何向下传递

核心写链只有 `InsertMessage` 把 `*sqlx.Tx` 传给 `mediaStore.LinkMessageMediaTx`；实现 [`media.Manager.LinkMessageMediaTx`](vscode://file/D:/codes/dev_proj/libredesk/internal/media/media.go:311:1) 使用 `tx.Stmtx(m.queries.LinkMessageMedia)`。其他跨 Manager 调用（SLA、Automation、Webhook、通知）不接收该事务。

本地 module cache 的 sqlx v1.4.0 中，`DB.BeginTxx`/`Beginx` 在底层 Begin 失败时明确返回 `nil, err`。因此下面 E 节所述 defer 顺序风险基于当前锁定版本源码，而不是模型猜测。

---

## 6. 从领域对象落到表、关系与约束

### 主干关系

```text
users(contact) 1 --- N conversations N --- 1 inboxes
                              | 0..1 assigned_user -> users
                              | 0..1 assigned_team -> teams
                              |
                              +--- N conversation_messages --- 1 users(sender)
                              +--- N conversation_participants --- 1 users
                              +--- N conversation_last_seen --- 1 users
                              +--- N applied_slas --- N sla_events

conversation_messages 1 --- N media（media.model_type='messages', model_id=message.id；无 FK）
```

### 核心约束及业务语义

| 表 | 关键 Schema | 对应业务规则 |
|---|---|---|
| `users` | `BIGSERIAL PK`；`user_type` enum；Agent email、Contact external ID/email 的部分唯一索引 | 活跃 Agent email 唯一；有 external ID 的 Contact 按 external ID 唯一；无 external ID 的 Contact 按 email 唯一。软删除行不参与这些唯一性。见 [`schema.sql`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:161:1)。 |
| `inboxes` | UUID unique；`channel` enum；`linked_email_inbox_id` 自引用 FK `SET NULL`；config JSONB | 渠道只能是 schema enum 值；被链接 Email Inbox 删除后引用清空。见 [`schema.sql`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:108:1)。 |
| `teams` | name UNIQUE；SLA/business hours FK `SET NULL`；assignment type enum | Team 名唯一；策略删除不删除 Team。见 [`schema.sql`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:128:1)。 |
| `conversations` | `BIGSERIAL PK`；UUID/reference unique；Contact/Inbox FK `CASCADE`；Assignee FK `SET NULL`；Status `RESTRICT NOT NULL`；Priority nullable | Contact/Inbox 删除会级联 Conversation；Agent/Team 删除只解除分配；被使用的状态不能删除。见 [`schema.sql`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:239:1)。 |
| `conversation_messages` | UUID unique；type/status/sender enum；Conversation、Sender FK `CASCADE NOT NULL`；`source_id` 仅普通索引 | Message 必须属于存在的 Conversation 和 Sender；删除任一方会级联 Message；DB 没有保证 source ID 唯一。见 [`schema.sql`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:301:1)。 |
| `conversation_participants` | `(conversation_id,user_id)` UNIQUE；双 FK `CASCADE` | 同一用户在同一会话只出现一次；任一父记录删除后关系消失。见 [`schema.sql`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:377:1)。 |
| `conversation_last_seen` | `(conversation_id,user_id)` UNIQUE；`last_seen_at NOT NULL` | 每个用户每会话只有一个读位置，允许原子 Upsert。见 [`schema.sql`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:406:1)。 |
| `media` | UUID unique；PostgreSQL enum/JSONB；`model_type/model_id` 普通复合索引，无 FK | 可按多态模型找附件；DB 不证明 `model_id` 必然指向 Message。见 [`schema.sql`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:417:1)。 |
| `applied_slas` | Conversation/Policy FK `CASCADE`；status enum；`UNIQUE(conversation_id) WHERE status='pending'` | 历史 SLA 可多条，但每个 Conversation 最多一个 pending SLA。见 [`schema.sql`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:555:1)。 |
| `sla_events` | Applied SLA/Policy FK `CASCADE`；metric/status enum | Event 必须依附合法 SLA；schema 没有“每个 Applied SLA 最多一个未完成 next_response”唯一约束。见 [`schema.sql`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:578:1)。 |

升级路径不是只靠初始 schema。`v2.3.0` 先用窗口函数去重旧的 pending Applied SLA，再创建部分唯一索引；`v2.0.0` 补 Message `(conversation_id, created_at)` 索引；`v0.8.5` 创建 last_seen 唯一索引。

**PostgreSQL 机制：**部分唯一索引只约束满足谓词的行，正适合“历史多条、活跃一条”。PostgreSQL 17 官方说明见 [Partial Indexes](https://www.postgresql.org/docs/17/indexes-partial.html)。

**MySQL 对比：**MySQL InnoDB 没有相同的任意谓词部分索引语法。可用“仅 pending 时生成 conversation_id，否则 NULL”的 generated column（生成列）再建 UNIQUE；MySQL 8.4 支持 generated column 的 UNIQUE 二级索引，见 [Secondary Indexes and Generated Columns](https://dev.mysql.com/doc/refman/8.4/en/create-table-secondary-indexes.html)。

---

### 6.3 业务不变量由数据库还是 Go 保证

| 业务不变量 | Go 保证 | SQL 语句保证 | DB Constraint 保证 | 结论 |
|---|---|---|---|---|
| Conversation 必须属于 Contact/Inbox/Status | 入口解析 ID/状态名 | `insert-conversation` 子查询 status ID | FK + `NOT NULL` | 最终由 DB 拒绝悬空引用。 |
| Conversation UUID/reference 不重复 | 无需 Go 预查 | DB 默认 UUID、sequence function | UNIQUE | DB 强保证。sequence 消耗不随事务回滚是 PostgreSQL 行为，不影响唯一性。 |
| 自动认领只能有一个胜者 | Go 检查 `RowsAffected` | `UPDATE ... WHERE assigned_user_id IS NULL AND assigned_team_id=$3` | 行更新锁/条件重检 | 该入口原子仲裁；失败者返回 `ErrConversationAlreadyAssigned`。 |
| 分配用户一定是 Agent | Hook 之后才 `GetAgent`；HTTP 未读取目标用户验证类型 | 直接写 `assigned_user_id` | FK 只指向 `users(id)`，不约束 `type` | 【代码分析】当前核心入口没有完整强保证。 |
| Team 改变后清空 User assignee | Go 在 Team SQL 成功后再调用 Remove | 两条独立 UPDATE | 无组合 CHECK/事务 | Team 变化时是两步；中间或第二步失败可保留“新 Team + 旧 User”。同 Team请求由 Handler提前返回，Manager 内也不会清 User。 |
| Snoozed 必须有未来时间 | Go 解析 duration 且要求 `>0` | 状态 SQL 写 `snoozed_until` | 无 `CHECK(status,snoozed_until)` | 【代码分析】通过该 Manager 可保证；直接 SQL/其他入口不受 DB 保护。 |
| resolved/closed 时间只首次落戳 | 无额外状态机 | `COALESCE(existing, CASE...)` | 无 | SQL 保留首次时间；ReOpen 不清空它们。 |
| Message 枚举、归属、Sender 合法 | Go 构造 enum 字符串 | `insert-message` | enum + FK + NOT NULL | DB 最终保证类型域和引用。 |
| 私有消息不进入 outgoing pending | `InsertMessage` 把 private 的 status 强制为 sent | pending scanner 过滤 `private=false` | 无跨列 CHECK | 【代码分析】Manager 路径保证；DB 本身允许 private+pending。 |
| 同一 `source_id` 只入库一次 | Incoming 先 `messageExistsBySourceID` | SELECT 后 INSERT | 只有普通 index | 【代码分析】串行通常去重，并发不构成强幂等。 |
| Message 与附件绑定同时成功 | Go 显式事务 | INSERT Message + UPDATE media | 同事务原子性；media 无 FK | 这两步同成同败；附件对象存储上传发生在事务外。 |
| Conversation last_message 指向最新消息 | commit 后 Go 调 Update | 无时间条件的 UPDATE | 无约束 | 【代码分析】并发 InsertMessage 的后写快照可能覆盖较新的快照。 |
| 每用户每会话只有一个 last_seen | Go 直接 Exec | `ON CONFLICT DO UPDATE` | 复合 UNIQUE | DB + Upsert 原子保证。 |
| 每会话最多一个 pending Applied SLA | Go 使用一条复杂 CTE 替换 | `apply-sla` 关闭/删旧再插新 | 部分 UNIQUE | 最终由 DB 保证；并发调用可能有失败者。 |
| 每 Applied SLA 最多一个未完成 next_response event | Go/SQL 使用 `WHERE NOT EXISTS` | 单条 INSERT SELECT | 无 partial UNIQUE | 【代码分析】两个并发语句可能都看不到对方未提交行并各插一条，需要并发实验。 |

---

## 7. 核心链路一：关键 SQL 如何改变数据

### `insert-conversation`

**调用者：**`Manager.CreateConversation`；上游包括 Agent 创建会话、Widget 创建、Incoming Email `findOrCreateConversation`。

**输入：**Contact/Inbox、Open 状态名、首条消息快照、subject、JSONB meta/custom attributes、时间窗起点和上限。

**修改：**CTE 取状态 ID、调用 `generate_reference_number`，再 `INSERT conversations ... SELECT ... WHERE count < max`，返回 id/uuid。见 [`queries.sql`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:7:1) 与 [`CreateConversation`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/conversation.go:374:1)。

**设计作用：**把“计数检查”和插入收敛到一个 SQL，避免 Go 层明显的两次往返；subject 可同时拼 reference。

**索引与约束：**Contact、Inbox、Status FK；UUID/reference UNIQUE；`contact_id` 和 `created_at` 分别有单列索引，但没有 `(contact_id,created_at)` 复合索引。

**并发：**在未显式提高隔离级别、未锁 Contact/配额行时，两个并发语句都可能在各自语句快照看到旧 count 并成功。它比 Go 的“先查再插”缩短窗口，但不等于严格限额。

### `insert-message` + `link-message-media`

**调用者：**`QueueReply`、Incoming/Widget 处理、Activity Message 等最终进入 `InsertMessage`。

**输入：**Message type/status、Conversation id 或 UUID、content/text_content、sender、private、content_type、source_id、JSONB meta、附件 IDs/inline UUIDs。

**修改：**CTE 解析 Conversation 后插入 Message；同一事务中把尚未绑定的 media 更新为 `model_type='messages', model_id=message.id`，inline media 补 `content_id`。见 [`insert-message`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:828:1)、[`link-message-media`](vscode://file/D:/codes/dev_proj/libredesk/internal/media/queries.sql:35:1)。

**设计作用：**防止“Message 已提交但已选附件仍未绑定”或“附件绑定了不存在/回滚的 Message”。

#### 关键代码：事务只覆盖 Message 与附件关系

```go
tx, err := m.db.Beginx()
// ... insert message ...
if err := m.mediaStore.LinkMessageMediaTx(tx, message.ID, message.Media, inlineUUIDs); err != nil {
    return err
}
if err := tx.Commit(); err != nil {
    return err
}
// participant、摘要、WebSocket、Webhook 从这里起都在事务外
```

**这段代码解决什么问题：** Message 行成功但附件关系只写了一部分，会让同一条业务消息形成不可解释的半成品。

**为什么这样写：** 两类数据库写共享一个 `*sqlx.Tx`，任一步失败都由 deferred rollback 撤销；只有 `Commit` 成功后，Message 才成为可对外传播的持久事实。

**如果没有这段机制会怎样：** 分开的自动提交可能留下“有 Message、缺附件关联”或“附件指向不存在 Message”的状态。

**当前工程代价：** 事务不能覆盖 WebSocket、Webhook、对象存储和后续摘要 SQL；这些副作用仍可能与已提交数据分叉。

**索引与约束：**Message FK/enum/UUID unique；Media `(model_type,model_id)` 服务回查；source_id 只有单列普通索引。

**并发：**同一 media 的两个事务都满足初始 `model_id=0` 时，会在同一行 UPDATE 上竞争；后执行者在 PostgreSQL 条件重检后通常更新 0 行，但 `LinkMessageMediaTx` 不检查 RowsAffected，因此两个 Message 都可能提交，只有一个实际拿到 media。这个结果需要数据库并发测试确认完整表现。

### `get-messages`

**调用者：**`GetConversationMessages`，Handler 先做 Conversation access check。

**输入：**Conversation UUID、private 可选过滤、message types、LIMIT/OFFSET。

**查询：**Message + Sender，并用相关子查询聚合 media；`ORDER BY m.created_at DESC`。见 [`queries.sql`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:779:1)。

**索引：**`(conversation_id, created_at)` 的列顺序与等值过滤 + 时间排序相匹配；Media `(model_type,model_id)` 对应附件子查询。是否实际使用必须 EXPLAIN。

【代码分析】查询同时计算 `COUNT(*) OVER()`；即使只返回一页，数据库仍需为匹配集计算窗口总数，`LIMIT` 不等于只处理 50 条。其实际成本取决于行数和执行计划，必须用 `EXPLAIN (ANALYZE, BUFFERS)` 验证。

**并发：**分页是 OFFSET；页面之间有新 Message 插入时可能重复/漏读，这是读一致性而非数据损坏。每一页单独开启一个 read-only 事务，`GetAllConversationMessages` 循环调用时并不共享同一快照。

### `get-outgoing-pending-messages` / `update-message-status`

**调用者：**`Manager.Run` 每个 scan interval 查询；Worker 发送后 `UpdateMessageStatus`。

**查询与修改：**扫描 `status='pending' AND type='outgoing' AND private=false`，只排除本进程 `sync.Map` IDs；没有 LIMIT、ORDER BY、`FOR UPDATE`、`SKIP LOCKED` 或数据库 claim。状态更新是 `UPDATE ... WHERE uuid=$2`，不校验旧状态。

**索引：**当前只有 status 单列索引；type/private 不在索引中。

**并发：**两个实例可读到同一 pending Message，各自调用外部渠道并无条件写 status。PostgreSQL 不会替业务选择唯一发送者。成功发送到 status 回写之间崩溃，也会被重扫。

【设计建议】若目标是多实例至少一次消费，可用短事务批量 `FOR UPDATE SKIP LOCKED` claim，并新增 processing/lease/attempt 字段；外部投递仍需稳定幂等键。PostgreSQL 官方说明 `SKIP LOCKED` 适合 queue-like 多消费者但不是通用一致视图，见 [SELECT locking clause](https://www.postgresql.org/docs/17/sql-select.html)。

### `claim-unassigned-conversation`

**调用者：**`autoassigner.Engine.assignConversations`。

**输入：**Conversation UUID、目标 user ID、扫描时读到的 expected team ID。

**修改：**仅在仍未分配且 Team 未变化时写 user；Go 检查 RowsAffected。

**索引与约束：**UUID UNIQUE 支持定位；assignee user FK 保证 user 存在，但不保证 user type 或 Team membership。

**并发时序：**T1/T2 都先读到 unassigned；T1 UPDATE 获得行更新权并提交；T2 等待后在最新行版本重检 WHERE，发现 `assigned_user_id IS NOT NULL`，更新 0 行，Go 返回 already assigned。该行为基于 PostgreSQL 17 默认 Read Committed 对并发 UPDATE 的条件重检规则，见 [Transaction Isolation](https://www.postgresql.org/docs/17/transaction-iso.html)。

### `update-conversation-status`

**调用者：**HTTP、Automation、AI/内部动作都可进 `Manager.UpdateConversationStatus`。

**输入：**UUID、状态名、Snooze deadline。

**修改：**同一条 UPDATE 写 status_id、首次 resolved_at、首次 closed_at、snoozed_until、updated_at。

**索引与约束：**UUID unique；status FK + NOT NULL。非法 status 名使子查询无行，最终会因 `status_id NOT NULL` 失败；Priority SQL 的目标列可 NULL，非法 priority 名则可能把 priority 清空。

**并发：**Go 的“先读旧状态、再更新、再发副作用”没有版本条件。两个并发不同状态请求是最后写入者胜出（Last Writer Wins）；两方的 Webhook/Activity 可能都基于各自读到的旧值，无法从数据库事务保证事件顺序。

### `apply-sla`

**调用者：**Team assignment/Automation 经 `conversation.Manager.ApplySLA` 到 `sla.Manager.ApplySLA`。

**修改：**一条 data-modifying CTE（数据修改 CTE）评估并关闭旧 pending、删除未形成结果的旧记录/未处理 warning，再插新 Applied SLA，最后更新 Conversation policy 和 cached deadline。见 [`sla/queries.sql`](vscode://file/D:/codes/dev_proj/libredesk/internal/sla/queries.sql:39:1)。

**约束：**部分 UNIQUE 是最终兜底；迁移先清理历史重复数据。

**并发：**多个 Apply 同时执行时不保证全部成功，但最终不能提交两个 pending。源码自带 `TestConcurrentApplySLA` 只要求至少一个成功、最终 pending=1；当前本地 PostgreSQL 环境未满足，该测试被 `SKIP`，所以数据库行为尚未在本地验证。

---

## 8. 核心链路二：事务边界覆盖了什么

### 核心事务

| 业务操作 | Begin → SQL → Commit/Rollback | 为什么必须同事务 | 事务外副作用 |
|---|---|---|---|
| Message + media 绑定 | `InsertMessage`: Beginx → insert-message → `LinkMessageMediaTx` → Commit；任一步失败 defer Rollback | 防止 Message 和已选附件绑定半完成 | participant Upsert、last_message 快照、查询完整 Message、WebSocket、Webhook；Incoming 附件上传更早发生 |
| SLA cached deadline 重算 | `RecomputeConversationNextSLADeadline`: Beginx → `SELECT conversations ORDER BY id FOR UPDATE` → UPDATE latest SLA deadline → Commit | 同一 Conversation 的并发重算必须串行；按 id 排序降低批量锁顺序不一致 | 调用它之前的 SLA event/met/breach 更新通常是别的语句 |
| Conversation 列表读取 | BeginTxx(ReadOnly) → 单次动态 SELECT → return 时 Rollback | 只包一条 SELECT；没有显式更强 isolation | 无 |
| Message 列表读取 | BeginTxx(ReadOnly) → 单次动态 SELECT → return 时 Rollback | 同上 | 附件 URL 签名等在返回路径 |

`GetConversations` 和 `GetConversationMessages` 都在检查 `BeginTxx` 的 `err` 之前执行 `defer tx.Rollback()`。结合 sqlx v1.4.0 Begin 失败返回 `nil, err`，函数返回时会对 nil Tx 调 Rollback，存在 panic 路径。正确顺序应先检查 err，再 defer。

### 重要的“没有事务包住的业务组合”

核心写入链显示以下业务组合跨越多个事务或事务外副作用：

- Create Conversation → Assignment → Queue first Message 不是一个事务；Queue 失败时用 DeleteConversation 补偿。
- Team assignment → clear User → Apply SLA 不是一个事务。
- Message status sent/failed → reply timestamps → SLA → Automation 不是一个事务。
- Conversation status → SLA evaluate → Webhook/Activity/WebSocket 不是一个事务。
- Applied SLA Event 状态更新 → cached deadline 重算是两个事务边界。

这些组合没有被更外层数据库事务包裹；提交后的 WebSocket、Webhook、Automation、通知与外部 I/O 也不属于同一事务。

### 其他事务只作为边界参照

Activity Log/User/Report 列表还使用只读事务，AI embedding/knowledge delete、AI Assistant CRUD、Help Center collection/article 写入也有写事务；迁移 v2.0.0 同样显式 `Begin`。这些链与本章的 Conversation、Message、Assignment 不变量没有直接调用关系，只作为“项目并非只有一种事务形态”的边界参照。

---

## 9. 并发下原子 SQL、锁与竞态窗口

### Isolation（隔离级别）

当前核心事务没有显式设置 `Isolation`，`sql.TxOptions` 只设置过 `ReadOnly: true` 或使用空 options。

**第三方机制：**因此 PostgreSQL 17 使用默认 Read Committed。每条普通 SELECT 取语句开始时的已提交快照；同一事务的后续 SELECT 可以看到期间新提交的数据。官方依据见 [Transaction Isolation](https://www.postgresql.org/docs/17/transaction-iso.html)。

### 两个 Agent 并发 claim

```text
T1: 扫描到 C(user=NULL, team=7)
T2: 扫描到 C(user=NULL, team=7)
T1: UPDATE C SET user=11 WHERE user IS NULL AND team=7 -> 1 row
T2: UPDATE 同一行 -> 等待 T1 -> 重检 WHERE -> 0 row
T1: hooks
T2: ErrConversationAlreadyAssigned
```

数据库只仲裁 Conversation 行归属；之前的 round-robin 取人和 active count 限额检查不在同一事务。

【代码分析】两个不同 Conversation 同时分给同一 Agent 时，都可能在写前读到未达上限，因此 `max_auto_assigned_conversations` 是软约束，不是严格并发配额。

### 两个 Worker/实例并发发送同一 Message

```text
实例 A SELECT pending M       实例 B SELECT pending M
A Inbox.Send 成功             B Inbox.Send 也可能成功
A UPDATE status=sent          B UPDATE status=sent/failed
```

没有行锁、claim 状态、版本列或旧状态条件；`sync.Map` 只属于一个 Manager 实例。

【代码分析】外部渠道可能收到重复；Message 最终状态由最后一次无条件 UPDATE 决定。需要双实例故障注入才能量化频率。

### 两封相同 source_id 并发进入

```text
T1 SELECT source_id=X -> none
T2 SELECT source_id=X -> none
T1 INSERT X -> success
T2 INSERT X -> success（无 UNIQUE 冲突）
```

schema 只有 `index_conversation_messages_on_source_id` 普通索引；`ProcessIncomingMessage` 的查重与 InsertMessage 不在同一事务。

【设计建议】先定义唯一作用域（全局、Inbox、Conversation、Sender）并清洗历史重复，再加合适 UNIQUE；空 source ID 应保持 NULL，避免把“未知”当成同一个业务键。

### 两条 Message 并发更新 last_message

```text
M1 先 INSERT(created_at=t1)，commit 后被暂停
M2 INSERT(created_at=t2>t1)，UPDATE conversation.last_message=M2
M1 恢复，执行无条件 UPDATE conversation.last_message=M1
```

【代码分析】Conversation 列表快照可能回退到旧消息，而 Message 表本身顺序正确。可在 SQL 中增加“仅当现有 last_message_at IS NULL 或 <= 新时间时更新”，但相同时间戳的稳定 tie-breaker 还需 Message id。

### SLA 并发

`RecomputeConversationNextSLADeadline` 先按 Conversation id 排序并 `FOR UPDATE`，锁到事务结束；其他写同一行者被阻塞。PostgreSQL 行锁规则见 [Explicit Locking](https://www.postgresql.org/docs/17/explicit-locking.html)。

【代码分析】这修复的是 cached deadline 并发覆盖，不自动把“event 更新 + deadline 重算”变成一个原子业务动作。另一个扫描器可以在两步之间看到短暂不一致，但后续重算/周期 sweep 可能修复；需故障注入验证恢复时间。

### 乐观并发与锁的当前边界

核心表有 `updated_at`，但核心 UPDATE 没有 `WHERE updated_at=$expected` 或 version 字段；它不是乐观锁（Optimistic Lock）版本号。当前 SQL 的 `FOR UPDATE` 只出现在 SLA Conversation 锁和 Help Center 行锁；核心链没有使用 `SKIP LOCKED/NOWAIT`。

【代码分析】Conversation、Message 与 Assignment 当前没有额外的 `FOR UPDATE` / `SKIP LOCKED` 悲观锁（Pessimistic Lock），也没有版本列驱动的乐观锁机制。

---

### 9.8 查询与索引是否匹配

| 索引 | 直接对应 SQL | 列顺序/谓词 | 主要用途 | 不能提前声称的内容 |
|---|---|---|---|---|
| `conversation_messages(conversation_id, created_at)` | `get-messages`、unread 子查询 | Conversation 等值在前，时间排序/范围在后 | 查询 | 未 EXPLAIN，不能声称一定消除 Sort 或一定被选中。 |
| `conversation_messages(status)` | pending scanner | 只有 status；SQL 还过滤 type/private | 查询候选 | pending 比例高时可能不选；不能凭 schema 断定瓶颈。 |
| `conversation_messages(source_id)` | incoming 查重 / thread references | 单列普通 | 查询 | 不提供唯一性。 |
| `conversations(uuid)` UNIQUE | 几乎所有详情/更新 | 单列高选择性 | 查询 + 业务标识唯一 | UUID 更新 SQL 预计可高效定位，但仍以 EXPLAIN 为准。 |
| `conversations(assigned_user_id)` / `(assigned_team_id)` | 列表和 autoassign 扫描 | 单列 | 查询 | Team-unassigned 同时要求 `assigned_user_id IS NULL`；当前无复合/partial index。 |
| `conversations(last_message_at)` | 默认列表 `ORDER BY DESC` | 单列 | 排序候选 | 叠加 assignee/status 过滤时未必能同时满足过滤和排序。 |
| `conversation_last_seen(conversation_id,user_id)` UNIQUE | unread 相关子查询、Upsert | Conversation 在前 | 查询 + 唯一性 | 精确双列匹配适配；未测列表规模下的相关子查询成本。 |
| `media(model_type,model_id)` | 每条 Message 聚合附件 | 两个等值条件顺序匹配 | 查询 | 未证明 N+1 式相关子查询在大页上的总成本。 |
| `applied_slas(conversation_id) WHERE status='pending'` UNIQUE | apply/get pending | 只索引 pending | 强业务约束 + 查询 | 它保证至多一条，不保证并发 Apply 都成功。 |
| `applied_slas(conversation_id)` + `created_at` 单列 | 列表 LATERAL latest SLA | 查询按 conversation 过滤、created_at 排序 | 查询候选 | 缺少 `(conversation_id, created_at DESC)`；是否值得加必须 EXPLAIN。 |

【代码分析】Conversation 列表不仅有 `COUNT(*) OVER()`，还对每行执行 unread count、latest Applied SLA、latest next-response event 和 mention 等相关/LATERAL 子查询。单看主表索引不能判断总体成本；EXPLAIN 时必须同时观察子计划的 loops 与实际行数。

**PostgreSQL 特有点：**Schema 还使用 GIN + `pg_trgm`、JSONB、数组、ENUM 和 data-modifying CTE。本章只在它们直接影响核心 SQL 时提及，不扩展成 PostgreSQL 教程。

---

## 10. 已确认的工程限制与待实验验证

### 当前验证状态

| 实验 | 当前状态 | 能得到的结论 |
|---|---|---|
| Conversation 纯 Go 测试 | 已通过 | 当前纯逻辑用例未发现断言失败 |
| SLA deadline 计算测试 | 已通过 | 基础截止时间计算已有测试覆盖 |
| PostgreSQL SLA 集成测试 | 环境未满足，已 `SKIP` | `TestConcurrentApplySLA`、SLA SQL、约束和索引尚未在真实数据库中验证 |
| 核心查询 `EXPLAIN` | 未执行 | Schema 与查询可做匹配分析，但不能声称 PostgreSQL 一定选择某索引 |

### 最小 EXPLAIN 清单

先用接近生产分布的数据 `ANALYZE`，再执行：

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT ... FROM conversation_messages
WHERE conversation_id = :cid
ORDER BY created_at DESC
LIMIT 50 OFFSET 0;

EXPLAIN (ANALYZE, BUFFERS)
SELECT ... FROM conversation_messages m
JOIN conversations c ON c.id=m.conversation_id
WHERE m.status='pending' AND m.type='outgoing' AND m.private=false;

EXPLAIN (ANALYZE, BUFFERS)
SELECT ... FROM conversations
WHERE assigned_team_id=:team AND assigned_user_id IS NULL
ORDER BY last_message_at DESC
LIMIT 50;
```

验证指标：actual rows、rows removed by filter、shared hit/read blocks、Sort/Top-N、扫描行数、planning/execution time。只比较现有索引和候选 partial/composite index，不先入库永久索引。

### 最小并发实验

1. **Claim**：两个连接同时执行同一 conditional UPDATE；断言一个 RowsAffected=1、一个=0。
2. **source_id**：两个事务 barrier 后同时运行“查无 → 插入”；查询重复数，验证当前竞态。
3. **Conversation 限额**：设 max=1，两连接同时 insert-conversation；观察是否得到 2 条。
4. **last_message**：T1 commit Message 后暂停，T2 完成快照更新，再恢复 T1；比较 `conversations.last_message_at` 与 `MAX(message.created_at)`。
5. **双实例 pending**：两个独立 Manager 指向同 DB 和记录型 fake Inbox；断言一次 pending 是否调用 Send 两次。
6. **SLA Apply**：恢复测试 DB 后单独运行：

```powershell
go test -count=1 -run '^TestConcurrentApplySLA$' -v ./internal/sla
```

7. **连接池**：在 30 max_open 下同时运行列表、pending scan、SLA sweep；采集 `db.Stats().WaitCount/WaitDuration`。这只是潜在约束验证，不预设瓶颈结论。

---

## 11. 面试表达

> LibreDesk 没有统一 Repository 层，而是让各业务 Manager 加载包内命名 SQL。像 Message 与附件关联这类同库写入由 Transaction 保证原子提交；自动认领则用带前置条件的 SQL 把检查和更新合在一次操作里。索引分析必须绑定真实 `WHERE/JOIN/ORDER BY`，是否实际采用仍要以 `EXPLAIN` 为准。需要特别区分数据库内一致性和外部副作用：Transaction 可以回滚 Message/Media 关系，却不能回滚已经发出的邮件或 Webhook。

## 本章必须记住的源码锚点

### [`ScanSQLFile`](vscode://file/D:/codes/dev_proj/libredesk/internal/dbutil/scanner.go:13:1)
**为什么必须记住：** 模块 SQL 从嵌入文件进入 prepared statement 的统一入口。  
**面试关联：** LibreDesk 的数据访问为何不是通用 Repository？

### [`InsertMessage`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:579:1)
**为什么必须记住：** 最清晰的写事务与事务外副作用案例。  
**面试关联：** `BEGIN` 到 `COMMIT` 究竟覆盖哪些步骤？

### [`claim-unassigned-conversation`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:436:1)
**为什么必须记住：** 条件 UPDATE 与 `RowsAffected` 共同完成原子认领。  
**面试关联：** 两个事务竞争同一行时为什么只有一个成功？

### [`apply-sla`](vscode://file/D:/codes/dev_proj/libredesk/internal/sla/queries.sql:39:1)
**为什么必须记住：** data-modifying CTE 在一条语句内切换 SLA。  
**面试关联：** SQL 原子性和唯一约束分别保证什么？

### [`conversation_messages`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:302:1)
**为什么必须记住：** 核心查询、外键和索引都围绕此表展开。  
**面试关联：** 索引“匹配查询”和“实际被选中”有什么区别？

### [`applied_slas`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:555:1)
**为什么必须记住：** 部分唯一索引把 pending SLA 数量变成数据库不变量。  
**面试关联：** 为什么只靠 Go 先查再写不够？

## 12. 面试追问

1. `InsertMessage` 为什么需要 Transaction？
2. `claim-unassigned-conversation` 如何缩小并发竞态窗口？
3. 为什么 pending 查询没有锁就无法支持多实例唯一领取？
4. 哪些不变量由数据库 Constraint 保证，哪些只由 Go 调用顺序保证？
5. 应如何用 `EXPLAIN (ANALYZE, BUFFERS)` 验证核心查询而不是凭索引名猜测？
