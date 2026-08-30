# LibreDesk HTTP、认证、授权与 API Layer 源码学习

## 1. 这个模块在 LibreDesk 中解决什么问题

前两章已经建立[领域规则](02-domain-conversation-message-state-machine-l4.md)与[数据库保证](03-postgresql-sql-transactions-concurrency-l4.md)；本章转到系统入口，解释外部 HTTP 请求如何恢复身份、经过动作权限与资源权限校验、调用业务 Manager，并被转换为统一响应。Conversation 内部状态不在这里重复，只追踪 API 边界如何保护并触发它。

## 本章核心源码

| 优先级 | 文件 / Symbol | 为什么必须读 |
|---|---|---|
| P0 | [`initHandlers` → `cmd/handlers.go:20`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:20:1) | 路由、中间件与 Handler 的总装配点 |
| P0 | [`auth` → `cmd/middlewares.go:112`](vscode://file/D:/codes/dev_proj/libredesk/cmd/middlewares.go:112:1) / [`perm` → `cmd/middlewares.go:142`](vscode://file/D:/codes/dev_proj/libredesk/cmd/middlewares.go:142:1) | 认证、动作权限和请求上下文的入口 |
| P0 | [`handleLogin` → `cmd/login.go:17`](vscode://file/D:/codes/dev_proj/libredesk/cmd/login.go:17:1) | 密码登录到 Session 创建的起点 |
| P0 | [`SaveSession` → `internal/auth/auth.go:259`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:259:1) | Redis Session 与 Cookie 建立 |
| P0 | [`ValidateSession` → `internal/auth/auth.go:342`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:342:1) | 后续请求如何恢复 User 身份 |
| P0 | [`enforceConversationAccess` → `cmd/conversation.go:720`](vscode://file/D:/codes/dev_proj/libredesk/cmd/conversation.go:720:1) | 动作权限之后的资源级访问控制 |
| P1 | [`sendErrorEnvelope` → `cmd/handlers.go:565`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:565:1) | 业务错误如何映射为 HTTP 响应 |

## 2. 一张图看懂整体机制

```text
HTTP Request → Router → auth / perm / rateLimit
                         ↓
                  Request Context 中的 App 与 User
                         ↓
                Handler 解析参数并校验资源权限
                         ↓
                     Manager → DB / Worker
                         ↓
                  统一 JSON 或 API Error
```

## 3. 必须先理解的核心概念

- **认证（Authentication）**：确认请求者是谁；LibreDesk 支持后台 Session 与 API Key 等入口。
- **授权（Authorization）**：确认已认证用户能否执行某个动作；既包含 RBAC（基于角色的访问控制），也包含 Conversation 资源范围校验。
- **CSRF（Cross-Site Request Forgery，跨站请求伪造）**：诱导已登录浏览器携带 Cookie 发出非本人意愿的写请求；Session 写操作需要额外 token 防护。
- **中间件（Middleware）**：在 Handler 前后统一执行认证、授权、限流等横切逻辑；本项目通过路由注册时的函数包装实现。

## 4. 源码阅读路线

**登录与身份恢复路线：** [`handleLogin`](vscode://file/D:/codes/dev_proj/libredesk/cmd/login.go:17:1) → `VerifyPassword` → [`SaveSession`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:259:1) → Cookie → [`auth`](vscode://file/D:/codes/dev_proj/libredesk/cmd/middlewares.go:112:1) → [`ValidateSession`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:342:1)。

**Conversation 查询授权路线：** [`initHandlers`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:20:1) → `perm("conversations:read")` → [`handleGetConversation`](vscode://file/D:/codes/dev_proj/libredesk/cmd/conversation.go:313:1) → [`enforceConversationAccess`](vscode://file/D:/codes/dev_proj/libredesk/cmd/conversation.go:720:1) → `GetConversation`。

**Message 创建路线：** 路由 `perm("conversations:send_message")` → [`handleSendMessage`](vscode://file/D:/codes/dev_proj/libredesk/cmd/messages.go:177:1) → 资源访问校验 → `QueueReply` / `InsertPrivateNote` → 统一响应。

**错误响应路线：** Handler / Manager error → `envelope.Error` → [`sendErrorEnvelope`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:565:1) → HTTP 状态与 JSON envelope。


## 5. HTTP 请求进入系统后的整体分工

### Server 与 Router 的组装

[`cmd/main.go:337`](vscode://file/D:/codes/dev_proj/libredesk/cmd/main.go:337:1) 创建 `fastglue.NewGlue()`，用 `g.SetContext(app)` 放入共享的 `*App`，调用 `initHandlers(g, wsHub)` 注册路由，然后把配置化的 `fasthttp.Server` 交给 `g.ListenAndServe`。Server 明确设置了 `ReadTimeout`、`WriteTimeout`、`MaxRequestBodySize`、`MaxKeepaliveDuration` 和 `ReadBufferSize`。`*App` 内持有 DB、Redis、User Manager、Conversation Manager、Auth、Authz、WebSocket Hub 等长生命周期依赖。

固定版本 `fastglue v1.8.0` 的 `NewGlue` 创建 `fasthttp/router v1.5.0`，设置 404/405 Handler，并开启 `SaveMatchedRoutePath`。`g.GET/POST/PUT/DELETE(path, handler)` 最终按 HTTP Method + Path 注册到该 Router；匹配出的 `{uuid}`、`{cuuid}` 等参数由 Router 写入 `fasthttp.RequestCtx.UserValue`，LibreDesk Handler 用同名 key 读取。

[`initHandlers`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:20:1) 没有注册 LibreDesk 自己的全局 before/after middleware；认证、授权和限流是在每条路由上通过高阶函数显式包裹，例如：

```text
POST /api/v1/auth/login
  rateLimit(handleLogin, "auth")

GET /api/v1/conversations/{uuid}
  perm(handleGetConversation, "conversations:read")

PUT /api/v1/conversations/{uuid}/status
  perm(handleUpdateConversationStatus, "conversations:update_status")
```

因此注册表达式的最外层最先执行。例如 `rateLimit(widgetAuth(handler), "widget")` 的顺序是限流 → Widget 认证 → Handler。本文四条核心链中，登录先限流；三个内部 API 先执行 `perm`，`perm` 内部再完成认证。

### API 层分工

可概括为四层，但边界不是严格的 Clean Architecture（整洁架构）：

1. Router：决定 Method/Path 与包装器。
2. Middleware wrapper：认证、CSRF（Cross-Site Request Forgery，跨站请求伪造）校验、端点权限和限流。
3. Handler：解析 Path/Query/Body、局部验证、资源级权限、调用 Manager、组装响应。
4. Manager + SQL：业务状态变化、事务、查询、WebSocket/Webhook/Automation 等副作用。

【代码分析】Handler 并非薄到只做协议适配。例如 `handleSendMessage` 同时决定 contact/agent/private 三种业务分支；`handleUpdateConversationStatus` 同时校验 snooze duration 并触发 Manager。面试时应描述为“模块化单体内的 Handler + Manager 分层”，不要声称存在统一 Service/Repository 抽象。

### 统一响应

`fastglue.Request.SendEnvelope` 固定返回 HTTP 200 和 `{"status":"success","data":...}`；`SendErrorEnvelope` 返回指定 HTTP Status 和 `{"status":"error","message":"...","data":null,"error_type":"..."}`。

`internal/envelope.NewError` 映射：General=500、Permission=403、Input=400、Data=422、Network=504、NotFound=404、Conflict=409、Unauthorized=401、RateLimit=429。[`cmd/handlers.go:565`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:565:1) 的 `sendErrorEnvelope` 只接受可直接断言为 `envelope.Error` 的错误；否则输出 500 和 `Error interface conversion failed`。

### 关键证据索引

| 关注点 | 本地路径与位置 | Struct / Function / SQL |
|---|---|---|
| Server 组装 | [`cmd/main.go:337`](vscode://file/D:/codes/dev_proj/libredesk/cmd/main.go:337:1) | `fastglue.NewGlue`、`SetContext`、`initHandlers`、`fasthttp.Server` |
| 四条路由 | [`cmd/handlers.go:22,58,65,73`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:22:1) | `rateLimit`、`perm` 与四个 Handler |
| 认证/授权包装 | [`cmd/middlewares.go:30,112,142,242`](vscode://file/D:/codes/dev_proj/libredesk/cmd/middlewares.go:30:1) | `authenticateUser`、`auth`、`perm`、`rateLimit` |
| Session/Cookie | [`internal/auth/auth.go:76,259,319,342,376`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:76:1) | `Auth`、`New`、`SaveSession`、`SetCSRFCookie`、`ValidateSession`、`DestroySession` |
| 登录 | [`cmd/login.go:17`](vscode://file/D:/codes/dev_proj/libredesk/cmd/login.go:17:1)、[`internal/user/user.go:146,310`](vscode://file/D:/codes/dev_proj/libredesk/internal/user/user.go:146:1) | `handleLogin`、`VerifyPassword`、`UpdateLastLoginAt` |
| Role/Permission 装载 | [`internal/user/queries.sql:27`](vscode://file/D:/codes/dev_proj/libredesk/internal/user/queries.sql:27:1)、[`internal/authz/authz.go:25,40`](vscode://file/D:/codes/dev_proj/libredesk/internal/authz/authz.go:25:1) | `get-user`、`Enforcer.Enforce`、`CanReadAssignment` |
| Conversation 查询 | [`cmd/conversation.go:313,720`](vscode://file/D:/codes/dev_proj/libredesk/cmd/conversation.go:313:1)、[`internal/conversation/conversation.go:422`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/conversation.go:422:1)、`queries.sql:182` | `handleGetConversation`、`enforceConversationAccess`、`GetConversation`、`get-conversation` |
| 状态修改 | [`cmd/conversation.go:570`](vscode://file/D:/codes/dev_proj/libredesk/cmd/conversation.go:570:1)、[`internal/conversation/conversation.go:956`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/conversation.go:956:1)、`queries.sql:455` | `handleUpdateConversationStatus`、`UpdateConversationStatus`、`update-conversation-status` |
| Message 创建/外发 | [`cmd/messages.go:177`](vscode://file/D:/codes/dev_proj/libredesk/cmd/messages.go:177:1)、[`internal/conversation/message.go:55,147,504,579`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:55:1)、`queries.sql:697,828` | `handleSendMessage`、`Run`、`sendOutgoingMessage`、`QueueReply`、`InsertMessage`、pending scan/insert SQL |
| 表与 Constraint | [`schema.sql:150-324`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:150:1) | `roles`、`users`、`user_roles`、`conversations`、`conversation_messages`、index/foreign key |
| Error mapping | [`internal/envelope/envelope.go:44`](vscode://file/D:/codes/dev_proj/libredesk/internal/envelope/envelope.go:44:1)、[`cmd/handlers.go:565`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:565:1) | `NewError`、`sendErrorEnvelope` |
| 固定依赖版本 | [`go.mod:42,47,49-50,71`](vscode://file/D:/codes/dev_proj/libredesk/go.mod:42:1) | fasthttp、fastglue、simplesessions、fasthttp/router |

---

## 6. 核心链路一：四类请求如何穿过 API 层

### `POST /api/v1/auth/login`：密码登录

#### 入口与调用链

真实调用链是：

```text
Client
→ fasthttp.Server
→ fastglue / fasthttp-router 按 POST + /api/v1/auth/login 匹配
→ rateLimit(handleLogin, "auth")
→ ratelimit.Limiter.Check（Redis 滑动窗口；失败时放行）
→ handleLogin
→ Request.Decode(loginRequest, "json")
→ user.Manager.VerifyPassword
   → SQL get-user（agent 类型）
   → bcrypt.CompareHashAndPassword
→ 检查 user.Enabled
→ auth.Auth.SaveSession
   → simplesessions.NewSession
   → Redis store Create + SetMulti(id/email/first_name/last_name)
   → Set-Cookie: libredesk_session
→ auth.Auth.SetCSRFCookie
   → Set-Cookie: csrf_token
→ user.Manager.UpdateLastLoginAt
   → SQL update-last-login-at
→ user.Manager.InvalidateAgentCache
→ activityLog.Login（失败只记录日志）
→ SendEnvelope(user)，HTTP 200
```

关键 Symbol：`cmd/handlers.go:initHandlers`、`cmd/middlewares.go:rateLimit`、`cmd/login.go:handleLogin`、`internal/user.Manager.VerifyPassword`、`internal/auth.Auth.SaveSession`、`SetCSRFCookie`、`internal/user.Manager.UpdateLastLoginAt`。

#### 参数、状态与不变量

Body 结构只有 `email`、`password`。JSON 解码失败或任一字段为空返回 400/InputException。`VerifyPassword` 用 `get-user` SQL 限制 `type='agent'`，密码用 bcrypt 校验；邮箱或密码错误都映射为同一个 400/InputException 文案。用户必须 `enabled=true` 才能继续。

成功后至少发生三类状态变化：Redis Session 写入；两个 Cookie 写入响应；DB 的 `users.last_login_at/updated_at` 更新。Activity log 是 best-effort（尽力而为），失败不改变 HTTP 成功。

【代码分析】登录链不是一个原子事务。`SaveSession` 和 Cookie 已成功后，`UpdateLastLoginAt` 若失败，Handler 返回 500，但浏览器可能已拿到有效 Session Cookie。客户端观察到“登录失败”，服务端实际已经建立会话，这是明确的部分成功窗口。

#### 真实错误路径

- 错误密码：`bcrypt.CompareHashAndPassword` → `VerifyPassword` 创建 InputError → `sendErrorEnvelope` → HTTP 400/InputException。
- 用户查询 DB 故障：Manager 包装为 GeneralError → HTTP 500/GeneralException。
- Redis Session 写入失败：`SaveSession` 返回第三方原始错误，Handler 将其重新包装为 GeneralError → HTTP 500。
- Activity log 写入失败：仅日志记录，仍 HTTP 200。

#### 最小验证实验

【设计建议】用一个真实 Redis + PostgreSQL 测三点即可，不做完整压测：

1. 正确/错误密码分别断言 200 与 400，并验证错误文案不区分邮箱和密码。
2. 登录成功后检查两个 `Set-Cookie` 属性，再带 Session + CSRF 调用受保护 PUT。
3. 在 Session 创建后让 `update-last-login-at` 失败，确认响应 500 时 Session 是否仍可使用，记录该部分成功语义。

### `GET /api/v1/conversations/{uuid}`：查询单个 Conversation

#### 入口与调用链

真实调用链是：

```text
Client
→ Server / Router（提取 uuid 到 UserValue）
→ perm(handleGetConversation, "conversations:read")
   → authenticateUser
      → 优先尝试 API Key；否则 ValidateSession
      → session user ID → GetAgentCachedOrLoad（补齐 roles/permissions/teams/enabled）
   → authz.Enforcer.Enforce(user, "conversations", "read")
   → 把精简 auth/models.User 写入 RequestCtx["user"]
→ handleGetConversation
   → 再次 GetAgentCachedOrLoad（恢复完整权限和团队）
   → enforceConversationAccess
      → conversation.Manager.GetConversation
         → SQL get-conversation（Conversation + Contact + Inbox + Status + Priority + SLA + CSAT）
      → authz.Enforcer.EnforceConversationAccess / CanReadAssignment
   → GetContactPreviousConversations(contactID, 10)
   → 过滤当前 Conversation
→ SendEnvelope(conversation)，HTTP 200
```

#### 权限、数据与错误

这里有两级授权，不是重复做同一件事：路由级必须拥有 `conversations:read`；资源级 `CanReadAssignment` 根据 `read_all`，或“分配给本人 + read_assigned”，或“属于分配团队 + read_team_all”，或“团队未分配个人 + read_team_inbox”，或“完全未分配 + read_unassigned”判定。

SQL `get-conversation` 通过 UUID cast 查主表，并联查 Contact、Inbox、Status、Priority、SLA、CSAT，标签通过子查询聚合。`conversations.uuid` 有 UNIQUE；Contact/Inbox/Status 等由外键约束。

Handler 没有先做 UUID 格式校验；SQL 执行 `NULLIF($2,'')::uuid`。合法但不存在的 UUID 由 `GetConversation` 映射为 404/NotFoundException；格式非法导致 PostgreSQL cast 错误，被 Manager 映射为 500/GeneralException。

`GetContactPreviousConversations` 的错误被 `_` 忽略，因此主 Conversation 已成功读取时，历史查询失败仍返回 200，只是 previous conversations 可能为空。这是该链中明确的错误丢失。

【代码分析】端点权限与资源权限分开是合理的：前者表示能力，后者表示数据范围。Middleware 已加载完整 User 后只向 Context 写入精简 User，Handler 又调用 `GetAgentCachedOrLoad`；缓存命中时成本较低，缓存未命中时可能重复 DB 加载。

#### 最小验证实验

【设计建议】创建“本人分配、同团队未分配个人、其他团队、完全未分配”四条 Conversation，给自定义角色组合各项 read 权限，做表驱动 HTTP 测试；另传 `not-a-uuid`，固定当前实际 500 行为，作为未来改成 400 时的回归基线。

### `PUT /api/v1/conversations/{uuid}/status`：修改 Conversation 状态

#### 入口与调用链

真实调用链是：

```text
Client
→ Server / Router（uuid）
→ perm(handler, "conversations:update_status")
   → authenticateUser
      → Session 路径先校验 csrf_token Cookie == X-CSRFTOKEN Header
      → ValidateSession → GetAgentCachedOrLoad
   → Enforce("conversations", "update_status")
→ handleUpdateConversationStatus
   → Decode(statusUpdateReq)
   → 校验 status；Snoozed 时校验 snoozed_until 可被 time.ParseDuration 解析
   → GetAgentCachedOrLoad
   → enforceConversationAccess（仍要求 conversations:read + assignment scope）
   → conversation.Manager.UpdateConversationStatus
      → 可选 statusID → statusStore.Get
      → 再校验 snooze duration > 0
      → GetConversation（读取变更前快照）
      → SQL update-conversation-status
      → EvaluateConversationSLA（错误仅记录）
      → GetConversation（读取变更后快照；错误仅记录）
      → TriggerEvent(webhook)
      → RecordStatusChange → InsertMessage(activity)
      → resolved 时触发 AI Agent、可选 CSAT
      → WebSocket broadcast
      → Automation evaluate
      → Widget broadcast
   → markAssignmentNotificationRead
→ SendEnvelope(true)，HTTP 200
```

#### 状态变化与业务不变量

`statusUpdateReq` 为 `status` + 可选 `snoozed_until`。当 status 为 `Snoozed`，Handler 要求非空 duration，Manager 再要求 duration > 0，并计算 `time.Now().Add(duration)`。

`update-conversation-status` SQL 通过 `conversation_statuses.name` 找 ID：

- 更新 `status_id`、`updated_at`。
- 第一次进入 category=`resolved` 时用 `COALESCE` 写 `resolved_at`，以后不覆盖。
- 第一次进入精确名称 `Closed` 时写 `closed_at`，以后不覆盖。
- 仅 `Snoozed` 保存 `snoozed_until`，切换到其他状态时清空。

相同且非 Snoozed 的状态会在 Manager 提前返回，避免重复活动/自动化；Snoozed 即使名称相同仍允许刷新时间。

【代码分析】“保留首次 resolved/closed 时间”是 SQL 直接保障的不变量；“每次状态变化都有对应 Activity/Webhook/Automation”并非原子保障。主 UPDATE 不在显式事务中，后续 Activity 写入失败会让 Handler 返回 500，但状态已经提交；SLA、变更后查询、CSAT 等部分副作用又是只记录错误继续。因此 API 的失败不能推导出状态未变化。

【合理推断】`UpdateConversationStatus` 的直接调用链没有事务、行锁或乐观版本条件。并发状态更新可能发生最后写入覆盖，且各请求基于各自读到的 `oldStatus` 产生副作用。是否会在真实负载造成错序，需要并发实验，不能仅凭源码定性为已发生故障。

Handler 只检查非空 status，没有检查它是否属于 DB 中的状态。不存在的名称会让 CTE 找不到 `status_id`；结合 `conversations.status_id NOT NULL`，该写入会成为数据库错误并被映射为 500，而不是输入 400。

#### 最小验证实验

【设计建议】对同一 UUID 并发发两个合法状态更新，在数据库、activity message、Webhook 捕获器和 WebSocket 事件中记录顺序；再注入 Activity insert 失败，验证 HTTP 500 时主状态是否已改变。这比先做大规模 Benchmark 更直接验证一致性语义。

### `POST /api/v1/conversations/{cuuid}/messages`：创建 Message

#### 入口与调用链

以普通 Agent 公共回复为主链：

```text
Client
→ Server / Router（cuuid）
→ perm(handler, "messages:write")
   → authenticateUser（API Key 或 Session；Session POST 要 CSRF）
   → Enforce("messages", "write")
→ handleSendMessage
   → GetAgentCachedOrLoad
   → enforceConversationAccess（读取 Conversation + assignment scope）
   → Decode(messageReq)
   → inbox.GetDBRecord + enabled 检查
   → sender_type / private 组合校验
   → sender_type=contact 时额外检查 messages:write_as_contact
   → getUnassociatedMedia
   → QueueReply
      → 再读取 Inbox，校验 enabled
      → Email 渠道整理 to/cc/bcc，并要求 to 非空，生成 source_id
      → template best-effort render
      → InsertMessage(status=pending)
         → 内容 HTML→纯文本、inline URL→CID
         → DB Transaction：INSERT conversation_messages + LinkMessageMediaTx
         → COMMIT
         → participant、conversation last_message、WebSocket、refetch、Webhook
→ markAssignmentNotificationRead
→ SendEnvelope(message)，HTTP 200，此时 message.status=pending

异步阶段：

conversation.Manager.Run 定时扫描 SQL get-outgoing-pending-messages
→ outgoingProcessingMessages（进程内 sync.Map）
→ buffered outgoingMessageQueue
→ MessageSenderWorker
→ sendOutgoingMessage
→ Inbox.Send（Email / LiveChat）
→ UpdateMessageStatus(sent 或 failed)
→ WebSocket + Webhook
```

#### 三个业务分支

`messageReq` 包括 attachments、message、private、to/cc/bcc、sender_type、mentions、echo_id。

- `sender_type=contact`：不能 private，且需额外 `messages:write_as_contact`；调用 `CreateContactMessage`，状态为 received。
- `private=true`：调用 `SendPrivateNote`，状态为 sent；mentions 插入失败仅记录日志，通知异步执行。
- 普通 Agent reply：调用 `QueueReply`，状态为 pending，等待 Worker 外发。

`InsertMessage` 的事务只覆盖 Message INSERT 与 media 关联。事务提交后的 participant、Conversation last message、广播、refetch、Webhook 不在同一事务中；部分调用失败只记录日志。

Body JSON 解码发生在资源授权之后；非法 JSON 的代码却调用 `SendErrorEnvelope(StatusInternalServerError, ..., InputError)`，所以 HTTP Status 是 500，而 `error_type` 是 InputException，存在协议层不一致。

#### 可靠性与并发

HTTP 200 的完成点是 pending Message 已入库，不是渠道已发送。Worker 外发失败会把状态改为 failed；`PUT .../retry` 只允许原发送者重试 failed 的 outgoing agent message，做法是把状态重新改为 pending。

【合理推断】扫描 SQL 只按 `status='pending'` 查询并排除传入的进程内 processing IDs，没有数据库 claim、`FOR UPDATE SKIP LOCKED` 或租约。单进程内 `sync.Map` 可避免同一 Manager 重复入队；如果部署多个应用实例，每个实例可能同时选到同一 pending 行。当前源码没有提供部署实例数事实，因此只能标记为多实例条件下的风险。

【合理推断】外部 `Inbox.Send` 成功后才更新 DB 为 sent；进程若在两步之间退出，数据库仍是 pending，之后可能再次外发。Email `source_id` 可形成 Message-ID，但当前源码不能证明第三方渠道具有去重保证，不能把它当作已证明的端到端幂等。

`echo_id` 仅放入 JSON meta；`conversation_messages` 没有以 echo_id 为键的 UNIQUE Constraint，当前 Handler/QueueReply/InsertMessage 链也没有查重。它不能由当前源码证明为写入幂等键。

#### 最小验证实验

【设计建议】不做吞吐 Benchmark，先做两个故障注入：

1. 让 fake Inbox.Send 记录发送成功后阻塞，再终止进程且不执行 status update；重启扫描器，观察同一 message UUID 是否再次发送。
2. 启动两个 Manager 共享同一数据库、各自独立 `sync.Map`，同时扫描一条 pending message，统计 fake channel 的发送次数。

---

## 7. 核心链路二：登录、Session 创建与身份恢复

### 主登录方式与 Credential 校验

源码提供密码登录与 OIDC（OpenID Connect，开放身份连接）登录；前端默认选择哪一种需要结合实际前端配置才能下“主方式”结论。就后端直接 Credential 校验链而言，`POST /api/v1/auth/login` 是本地邮箱 + bcrypt 密码链。

`VerifyPassword` 的 `get-user` SQL 同时聚合 Role、Permission 和 Team，但登录响应使用该 User；Session 内只保存 ID、email、first_name、last_name，不保存密码、Role、Permission 或 Team。

### Session 创建与 Cookie

`internal/auth.New` 配置：Session ID 长度 64、Cookie 名 `libredesk_session`、HttpOnly=true、Secure 由 `app.server.disable_secure_cookies` 反向控制、SameSite=Lax、MaxAge=session_lifetime（默认 9h）；Redis store TTL 同为 lifetime，且 `extend=false`，访问不会滑动续期。

`simplesessions v3.0.0` 为未显式设置的 Cookie Path 补 `/`；`NewSession` 生成随机字母数字 ID、先创建 store entry，再写 Cookie。`SetMulti` 把四个字段写入 Session store。

【代码分析】Cookie 只承载随机 Session ID，身份数据在服务端 Redis；这是 server-side session（服务端会话），不是 JWT（JSON Web Token）。禁用用户的即时生效依赖后续请求重新加载 Agent（缓存或 DB）并检查 `Enabled`，而不只是信任 Session 快照。

### 后续请求恢复 User

恢复链为：

```text
libredesk_session Cookie
→ Auth.ValidateSession
→ simplesessions.Acquire + GetMulti
→ auth/models.User（仅 ID/email/name）
→ user.GetAgentCachedOrLoad(ID)
→ get-user SQL / 本地 agentCache
→ 完整 User：Enabled + Roles + Permissions + Teams
→ RequestCtx["user"] 再写入精简 User
```

`RequestCtx` 中另写 `auth_method=session|api_key|signed_url|public`。在 Message 查询链中，它用于决定是否向 Agent Session 隐藏 CSAT UUID。

【代码分析】User 的可信授权数据来源是 `GetAgentCachedOrLoad`，而不是 Session 中的姓名/邮箱。Role 或 Team 变更后的生效时间受 agent cache 生命周期和显式 invalidation 影响；本文未扩展到缓存专项。

### Logout

`GET /logout` 经 `auth` 后调用 `DestroySession`，删除 Redis Session 并下发清 Cookie，然后返回 302；Activity log 失败不阻断。它还设置 no-cache headers。

【代码分析】Logout 是改变状态的 GET，因此不会进入 `authenticateUser` 仅针对 POST/PUT/DELETE 的 CSRF 校验。SameSite=Lax 会降低部分跨站场景，但当前实现本身没有对 logout 做 token 校验。这更适合作为安全设计改进点，而不是声称已存在可利用漏洞。

### OIDC 外围链

`GET /api/v1/oidc/{id}/login` 生成 32 字符 state，连同 next 写进 Session，再用 provider 配置生成授权 URL。Callback 从 Session 读 state 并与 query state 比较，交换 code，使用当前 provider verifier 验证 ID Token，按 email 查本地 Agent，要求 enabled 且 type=agent，最后调用同一个 `SaveSession`。

`OIDCclaim` 解析 `email_verified`，但 `handleOIDCCallback` 没有检查该字段；本地账号匹配只使用规范化后的 email。当前 LibreDesk OIDC 调用链也未显示 nonce 的生成/校验；不能据此推断 provider 或依赖内部没有其他校验。

Email Inbox 的 OAuth 是另一条业务链：`handleOAuthAuthorize` 本身受 `inboxes:manage` 保护，state 与 client credentials 暂存在 Redis 15 分钟，Callback 取出后删除 state。它不是 Agent 登录机制。

---

## 8. 核心链路三：动作权限与资源权限如何叠加

### 不是“只看目录名”的 RBAC 结论

实际模型是：

```text
Role.permissions TEXT[]
        ↓ user_roles 多对多
get-user SQL 对多个 Role 的权限做 DISTINCT 聚合
        ↓
User.Permissions []string
        ↓
Enforcer.Enforce = slices.Contains("object:action")
        ↓
Conversation 资源再叠加 User.ID、User.Teams、assigned_user_id、assigned_team_id
```

它确实有 Role-Based Access Control（RBAC，基于角色的访问控制）的“用户—角色—权限”部分，但运行时 Enforcer 检查的是已展开的 permission 字符串；Conversation 读取又叠加 assignment/team 的资源范围规则。因此准确说法是“Role 聚合权限 + 资源属性/关系约束”，而不是把 `internal/authz` 直接等同于某个标准 RBAC 框架。

### 路由权限、资源权限、业务分支权限

三层分别位于：

1. `perm(handler, "obj:act")`：端点能力。
2. `enforceConversationAccess`：Conversation 资源范围。
3. Handler 内额外权限：如以 Contact 身份创建 Message 还要 `messages:write_as_contact`。

查询、修改状态、发消息都会先通过各自路由权限，随后调用 `enforceConversationAccess`。所以拥有 `messages:write` 但没有 `conversations:read` 或不满足 assignment scope，仍不能向该 Conversation 发消息。

`schema.sql` 默认 Agent Role 同时包含 `conversations:read_all` 和其他 read scope 权限，因此初始默认 Agent 的资源检查会被 read_all 提前放行；自定义 Role 或后续 Role 修改仍可形成更窄范围。

### 关键数据约束

`roles.name` UNIQUE；`user_roles(user_id, role_id)` UNIQUE；外键删除 User/Role 时级联删除关联；`users` 的未删除 Agent email 有部分 UNIQUE index。Team membership 来自 `team_members`，`get-user` 聚合为 `User.Teams`。

【代码分析】权限 union（并集）意味着多个 Role 只增加能力，没有显式 deny 规则。源码中的 Enforcer 也没有优先级、条件表达式或 deny override。这是当前实现事实导出的模型特征，不代表所有 RBAC 都如此。

---

## 9. API 边界中的 Context、校验与安全机制

需要区分三类 Context：

| 载体 | 写入者 | 内容 | 消费者 |
|---|---|---|---|
| `fastglue.Request.Context` | `g.SetContext(app)` | 共享 `*App` 依赖容器 | 所有 Middleware/Handler 的 `r.Context.(*App)` |
| `fasthttp.RequestCtx.UserValue` | Router | `uuid`、`cuuid`、`id` 等 Path 参数；matched route | Handler |
| `fasthttp.RequestCtx.UserValue` | Middleware | `user` 精简身份、`auth_method`、部分限流标记 | Handler/下游包装器 |

`authenticateUser` 内的完整 `user/models.User` 含 Roles、Permissions、Teams；`auth`/`perm` 写入 Context 的却是 `auth/models.User`，只含 ID、Email、FirstName、LastName。需要资源权限的 Handler 会用 ID 再次 `GetAgentCachedOrLoad`。

【代码分析】这避免把可变的权限快照长时间挂在 Session，也减少 Handler 误用 Session 自带权限的可能；但在单次请求内丢弃刚加载的完整 User，造成重复 cache lookup/潜在 DB lookup。更清晰的设计可在 Request Context 保存一个只读 `Principal`，包含 ID、auth method、permissions、team IDs，并让 Handler 不再自行恢复。

没有使用标准库 `context.Context` 逐层传 DB timeout；例如 `GetConversationMessages` 和若干 read-only transaction 使用 `context.Background()`。HTTP 取消是否能中断这些 DB 操作，当前链没有源码证据证明可以。

---

### 9.1 参数校验与错误传播

### 参数解析位置

当前 API 没有统一 Validator：

- Path：Router 写 `UserValue`，Handler 自行 `strconv.Atoi`，或直接把 UUID 字符串交给 SQL。
- Query：Handler 直接用 `QueryArgs.Peek/GetBool/PeekMulti`。`getPagination` 对非法数字静默回退 page=1/page_size=30，并把 page_size 上限限制为 500。
- Body：多数 Handler 用 `r.Decode(&req, "json")`，部分直接 `json.Unmarshal(PostBody)`；必填、枚举和跨字段条件由 Handler 手写，Manager 有时重复关键验证。

固定版本 fastglue 的 `Decode` 在 Content-Type 含 JSON 时使用标准 `json.Unmarshal`；不拒绝未知字段，也没有自动执行 struct validation tag。非 JSON/XML 时会从 PostArgs 扫描。

### 错误传播矩阵

| 来源 | 传播 | 最终表现 | 分类 |
|---|---|---|---|
| 登录 JSON 错 | Handler 直接 SendErrorEnvelope | 400/InputException | |
| 登录错误密码 | Manager InputError → sendErrorEnvelope | 400/InputException | |
| Session 无效 | authenticateUser GeneralError → `auth/perm` 强制改 status | 401，但 error_type=GeneralException | |
| CSRF mismatch | PermissionError → `auth/perm` | 403/PermissionException | |
| 无端点 permission | `perm` | 403/PermissionException | |
| 无 Conversation scope | enforceConversationAccess PermissionError | 403/PermissionException | |
| Conversation 不存在 | Manager NotFoundError | 404/NotFoundException | |
| Message JSON 错 | Handler 显式 status 500 + InputError type | 500/InputException | |
| 普通 DB 故障 | Manager GeneralError | 500/GeneralException | |
| 非 envelope.Error 进入 sendErrorEnvelope | type assertion 失败 | 500/GeneralException，消息为 conversion failed | |
| Rate limit 超限 | Limiter 自己写 body 后返回 error | 429，body 无 error_type/data | |

【代码分析】系统区分了输入、权限、未找到、冲突、基础设施等错误类型，但映射并非完全一致：认证失败底层构造 GeneralError 后由 Middleware 改 HTTP 401，却仍发送 GeneralException；Message JSON 错误是 500/InputException；Redis 限流错误包络又绕过统一 Envelope。面试中可评价为“已有 typed error 雏形，但缺少单一错误翻译边界”。

【代码分析】`sendErrorEnvelope` 用直接 type assertion 而不是 `errors.As`，一旦上层用 `%w` 包装 `envelope.Error`，错误类型会丢失并退化为 conversion failed。当前四条链中大部分 Manager 主动返回未包装的 envelope.Error，但这个基础设施约束值得测试。

---

### 9.2 Cookie、CSRF、API Key 与限流

### Session Cookie 与 CSRF

Session Cookie：`libredesk_session`、Path `/`、HttpOnly、SameSite=Lax、默认 Secure、MaxAge 默认 9h。CSRF Cookie：`csrf_token`、Path `/`、默认 Secure、HttpOnly=false；代码没有显式设置 SameSite 或 MaxAge。

CSRF 使用 double-submit cookie（双重提交 Cookie）：对 Session 路径的 POST/PUT/DELETE，要求 Cookie 与 `X-CSRFTOKEN` 完全相等。API Key 认证优先，一旦成功就不做 CSRF。登录路由不经 auth，因此不执行该校验。

【代码分析】CSRF token 没有在服务端绑定到 Session；防护依赖攻击者不能读取/设置匹配的同源 Cookie/Header。Middleware 在 mismatch 时把 cookie token 和 header token 原值写入错误日志，这是敏感 token 暴露风险，建议只记录是否存在及短哈希，不记录原值。

校验方法集合不含 PATCH；当前 `initHandlers` 没有注册 PATCH，但若未来新增 PATCH 并复用 `auth/perm`，它不会自动获得这段 CSRF 检查。

### API Key

`authenticateUser` 优先解析 `Authorization` 的 Basic 或 `Token key:secret`。`ValidateAPIKey` 按 `users.api_key` 查 enabled 且未删除用户，使用 SHA-256 后的 secret 做 constant-time compare；兼容旧 bcrypt hash 并在成功时升级。成功后 best-effort 更新 `api_key_last_used_at`。

API Key 生成 32 字符 key + 64 字符随机 secret，DB 保存 key 和 secret hash；生成端点只在创建时返回明文 secret。`users.api_key` 有普通 index，不是 UNIQUE Constraint。

【代码分析】有效 API Key 绕过 CSRF 是合理的非 Cookie 客户端语义。若请求带了可解析但无效的 API Key，不会回退 Session；若 Authorization 无法解析或缺一半，则代码会继续尝试 Session。这一优先级应进入集成测试。

### Rate Limit

登录、OIDC、密码重置等 auth 路由使用 `auth` 规则；普通内部 API 没有统一限流。Limiter 以 `ruleName + client IP` 为 Redis key，用 ZSET 做约 60 秒滑动窗口，返回 X-RateLimit headers；Redis pipeline 失败时直接 `return nil`，属于 fail-open（故障放行）。

【代码分析】fail-open 是可用性优先的明确行为，但 Redis 故障时登录防爆破能力会消失。是否可接受取决于威胁模型，应通过故障注入确认告警，而不是只靠代码阅读判断生产风险。

### OIDC / OAuth / 其他

OIDC 登录有 state 校验、ID Token verifier、Agent 类型和 enabled 校验；Provider discovery/Token 请求使用带 SSRF（Server-Side Request Forgery，服务端请求伪造）控制和超时的 HTTP Client。Inbox OAuth state 有 15 分钟 TTL 且回调后删除。

当前 HTTP/Auth 请求链没有统一的 Trace（分布式追踪）或 HTTP Metrics（指标）中间件；这只描述该请求边界，不外推仓库之外的部署设施。

---

## 10. 已确认的工程限制与待实验验证

- 认证确认请求者身份，授权还必须同时覆盖动作权限与具体资源范围。
- Handler 负责协议解析和资源边界，Manager 负责领域状态与事务。
- Session Cookie 写请求需要 CSRF 防护；API Key 的威胁模型不同。
- `sendErrorEnvelope` 只接受未包装的具体 `envelope.Error`；wrapped error 的 HTTP 语义需要专项验证。
- Conversation 状态更新没有版本条件；并发最后写入覆盖和副作用顺序尚需真实 PostgreSQL 实验。

| 实验问题 | 为什么需要实验 | 最小验证方法 | 成功 / 失败分别说明什么 |
|---|---|---|---|
| wrapped `envelope.Error` | 直接类型断言可能丢失稳定错误类型 | 用 `fmt.Errorf("ctx: %w", envelope.NewError(...))` 调统一出口 | 保留 4xx 表示映射支持包装；返回 500 表示当前契约只认具体值 |
| 同一 Conversation 并发改状态 | 两个请求可能基于相同旧状态产生副作用 | barrier 同时提交两个目标状态，记录 DB、Activity、Webhook 顺序 | 顺序稳定说明存在未识别仲裁；结果分叉则确认最后写入与副作用窗口 |
| Session / CSRF 组合 | 中间件分支多，静态调用链不能替代协议测试 | 覆盖缺 Cookie、缺 Header、错误 Token、API Key 四组请求 | HTTP 状态和 envelope 符合约定才说明边界可依赖 |

## 11. 面试表达

> LibreDesk 的 HTTP 路由通过函数包装组合认证、权限与限流。认证负责从 Session 或 API Key 恢复用户，`perm` 处理动作级 RBAC；涉及 Conversation 的 Handler 还要做资源级访问校验。Handler 从统一 `App` 请求上下文取得业务依赖，解析参数后调用 Manager，最后把领域错误映射为 API 响应。Cookie Session 的写请求还需要 CSRF token，因为浏览器会自动携带 Cookie。这种显式包装容易沿路由追踪，但权限、资源校验和错误映射分散在多层，新增端点时必须逐层保持契约一致。

## 本章必须记住的源码锚点

### [`initHandlers`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:20:1)
**为什么必须记住：** 路由和所有 API 边界包装器的地图。  
**面试关联：** 中间件执行顺序由什么决定？

### [`auth`](vscode://file/D:/codes/dev_proj/libredesk/cmd/middlewares.go:112:1) / [`perm`](vscode://file/D:/codes/dev_proj/libredesk/cmd/middlewares.go:142:1)
**为什么必须记住：** 身份恢复与动作权限的第一道门。  
**面试关联：** Authentication 与 Authorization 为什么不能混为一谈？

### [`SaveSession`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:259:1)
**为什么必须记住：** Redis Session、Cookie 与 CSRF token 的建立点。  
**面试关联：** 浏览器 Cookie 为什么还需要 CSRF 防护？

### [`ValidateSession`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:342:1)
**为什么必须记住：** 每次受保护请求恢复身份的核心。  
**面试关联：** Redis 故障会怎样传播到认证？

### [`enforceConversationAccess`](vscode://file/D:/codes/dev_proj/libredesk/cmd/conversation.go:720:1)
**为什么必须记住：** 在 RBAC 之后检查具体 Conversation 是否可读写。  
**面试关联：** 为什么只有 `conversations:read` 仍不够？

### [`sendErrorEnvelope`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:565:1)
**为什么必须记住：** 错误类型到 HTTP 响应的最终边界。  
**面试关联：** 直接类型断言会怎样影响 wrapped error？

## 12. 面试追问

1. Authentication 与 Authorization 在当前调用链中分别发生在哪里？
2. 只有 `perm("conversation:update")` 为什么仍不足以保护某个 Conversation？
3. Session Cookie 写请求为什么需要 CSRF 防护，而 API Key 路径不同？
4. Handler、Middleware 和 Manager 各自应该负责哪类校验？
5. API 错误怎样既保留内部原因又避免向客户端泄露敏感信息？
