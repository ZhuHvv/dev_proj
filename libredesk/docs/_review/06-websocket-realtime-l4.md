# LibreDesk WebSocket 实时通信源码学习

## 1. 这个模块在 LibreDesk 中解决什么问题

[Message](02-domain-conversation-message-state-machine-l4.md) 的最终事实保存在 PostgreSQL，[上一章](05-go-concurrency-reliability-l4.md)已经解释后台 Worker 如何推进状态；本章只继续追踪状态提交后如何尽快通知客服界面和 Widget。重点是 WebSocket 如何把业务事件推到当前进程中的在线连接，以及“实时通知”为什么不等于“可靠消息存储”。

## 本章核心源码

| 优先级 | 文件 / Symbol | 为什么必须读 |
|---|---|---|
| P0 | [`Hub` → `internal/ws/ws.go:15`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/ws.go:15:1) | Agent 连接、订阅与广播的进程内注册表 |
| P0 | [`Client` → `internal/ws/client.go:22`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/client.go:22:1) | 单连接的读循环、写循环和有界发送队列 |
| P0 | [`BroadcastMessage` → `internal/ws/ws.go:209`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/ws.go:209:1) | 业务事件如何按订阅扇出 |
| P0 | [`Client.SendMessage` → `internal/ws/client.go:221`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/client.go:221:1) | Agent 慢连接的过载处理 |
| P0 | [`safeConn.WriteMessage` → `cmd/widget_ws.go:87`](vscode://file/D:/codes/dev_proj/libredesk/cmd/widget_ws.go:87:1) | Widget 连接如何用互斥锁（Mutex）串行写 |
| P1 | [`LiveChat.BroadcastMessageToClients` → `livechat.go:393`](vscode://file/D:/codes/dev_proj/libredesk/internal/inbox/channel/livechat/livechat.go:393:1) | Widget 侧按联系人/会话广播 |
| P1 | [`UpdateMessageStatus` → `message.go:416`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:416:1) | 数据库提交后触发实时状态事件的边界 |

## 2. 一张图看懂整体机制

```text
HTTP / Message Worker 完成业务变化
              ↓
         ws.Hub 查找订阅者
          ↙               ↘
Agent Client channel    Widget safeConn
single writer goroutine   mutex 串行写
          ↓               ↓
       WebSocket frame；断线后仍以 HTTP + DB 重建事实
```

## 3. 必须先理解的核心概念

- **单写者（Single Writer）**：同一 WebSocket 连接只由一个 goroutine 真正写帧，避免并发写破坏协议状态。
- **扇出（Fan-out）**：同一业务事件复制并发送给多个订阅连接；当前 Hub 的连接表只存在本进程。
- **订阅注册表（Subscription Registry）**：记录某连接正在关注哪些 Conversation，用于缩小广播范围。
- **背压（Backpressure）**：慢客户端导致发送队列堆积时的限制策略；本章关注它在 Agent 与 Widget 两条路径上的差异。

## 4. 源码阅读路线

**Agent 连接路线：** WebSocket Handler → [`Hub`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/ws.go:15:1) 注册 → [`Client`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/client.go:22:1) 的 `Listen` / `Serve` → 断线清理。

**Agent 订阅与广播路线：** [`SubscribeOpenConv`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/ws.go:99:1) → 业务提交 → [`BroadcastMessage`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/ws.go:209:1) → [`Client.SendMessage`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/client.go:221:1) → 单写者 goroutine。

**Widget 推送路线：** HTTP / Message Worker 完成状态变化 → `LiveChat.Send` / `BroadcastMessageToClients` → client channel → [`safeConn.WriteMessage`](vscode://file/D:/codes/dev_proj/libredesk/cmd/widget_ws.go:87:1)。


## 5. Agent 与 Widget 两套连接模型

```text
                         process-global
                    ┌────────────────────┐
authenticated agent │ ws.Hub             │
GET /ws ───────────>│ clients[userID][]  │
                    │ convSubs* maps     │
                    └──────┬─────────────┘
                           │ *ws.Client per connection
                           │ Send chan WSMessage (128)
                           ├── Listen: socket -> inbound dispatch
                           └── Serve:  Send/ping -> socket

widget visitor             per livechat inbox instance
GET /widget/ws ─join────>┌──────────────────────────┐
                         │ livechat.LiveChat        │
                         │ clients[contactID][]     │
                         └────────┬─────────────────┘
                                  │ *livechat.Client
                                  │ Channel chan []byte (128)
                                  └── forwarder -> safeConn -> socket
                         Upgrade callback itself runs read loop
```

### Agent Hub

`Hub` 由 `cmd/init.go:initWS` 在启动时创建一次，注入 `conversation.Manager`、notification dispatcher 和 HTTP handler；`wsHub.SetConversationStore(conversation)` 建立 typing/授权反向依赖。见 [`cmd/main.go:249-264,332-339`](vscode://file/D:/codes/dev_proj/libredesk/cmd/main.go:249:1)、[`cmd/init.go:408`](vscode://file/D:/codes/dev_proj/libredesk/cmd/init.go:408:1)。

它不是 goroutine confinement（单 goroutine 独占状态）模型：`Hub` 没有自己的 event loop 或 register/unregister channel，多个请求/worker goroutine 直接调用方法，依靠两把 `sync.RWMutex`：

- `clientsMutex`：`clients map[int][]*Client`；
- `subsMu`：四张 subscription map。

`RemoveClient` 的锁顺序为 `clientsMutex → subsMu`；当前 subscription 方法只取 `subsMu`，直接调用链中未发现反向获取 `subsMu → clientsMutex` 的路径。证据：[`internal/ws/ws.go:15-29,78-186`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/ws.go:15:1)。

同一个 user ID 可保存多个连接，没有 agent 侧连接数上限。`KickUser` 复制 slice 后释放读锁，再逐连接关闭；`CloseAll` 同样先做快照（Snapshot）。见 [`internal/ws/ws.go:55`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/ws.go:55:1)。

### Agent subscription registry

list subscription 与 open-conversation subscription 分开：

- `SubscribeListReplace` 完整替换当前 client 的列表来源订阅；
- `SubscribeOpenConv` 只允许一个当前打开会话，并替换旧值；
- `ListSubscribers` 求两个集合并集，避免同一 client 重复推送；
- `ClearClientSubs` 使用反向表移除所有引用。

前端列表最多提交 500 个 UUID，服务端截断后调用 `FilterAuthorizedListUUIDs`。打开会话也调用同一授权函数。对应 SQL 按 `conversations:read*` 权限、assigned user/team 和未分配条件过滤。证据：[`internal/ws/client.go:117`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/client.go:117:1)、[`internal/ws/ws.go:78`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/ws.go:78:1)、[`internal/conversation/conversation.go:2164`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/conversation.go:2164:1)、[`internal/conversation/queries.sql:999`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:999:1)。

typing 是一个例外：agent 的 `handleTyping` 仅校验 JSON 和 UUID 非空，不逐帧检查该会话授权；源码注释明确把它视为短暂、外观性数据。非 private typing 还能转发给 Widget。见 [`internal/ws/client.go:158`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/client.go:158:1)、[`internal/ws/ws.go:231`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/ws.go:231:1)。

### Widget registry

每个已初始化 livechat inbox 各有一个 `LiveChat` 实例及独立 `clients map[string][]*Client`，不是全局 Widget Hub。`string` key 实际由 contact user ID 十进制字符串生成。每用户最大 10 个连接；`AddClient` 创建容量 128 channel。见 [`internal/inbox/channel/livechat/livechat.go:127-185,311-330`](vscode://file/D:/codes/dev_proj/libredesk/internal/inbox/channel/livechat/livechat.go:127:1)。

Widget Upgrade 允许 cross-origin（跨源），但 join 阶段检查 inbox 存在且 enabled、blocked IP、session token、session/inbox 归属、user 存在且 enabled，以及 inbox 实例确为 `*livechat.LiveChat`。见 [`cmd/websocket.go:44`](vscode://file/D:/codes/dev_proj/libredesk/cmd/websocket.go:44:1)、[`cmd/widget_ws.go:210`](vscode://file/D:/codes/dev_proj/libredesk/cmd/widget_ws.go:210:1)。

【代码分析】因此 Widget 的安全边界不是 Origin，而是 join token 与 inbox/contact 绑定；Upgrade 成功不代表已注册业务连接。

## 6. 核心链路一：连接、注册、读写与清理

### Agent：connect → cleanup

1. 路由 `GET /ws` 先过 `auth`。`authenticateUser` 支持 API key 或 session；session/user 无效、过期、disabled 都不能进入 handler。GET 不执行 CSRF（跨站请求伪造）token 比对，但 upgrader 另做 Origin 检查。证据：[`cmd/handlers.go:345`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:345:1)、[`cmd/middlewares.go:27-81,110-137`](vscode://file/D:/codes/dev_proj/libredesk/cmd/middlewares.go:27:1)。
2. `agentUpgrader.CheckOrigin` 要求 Origin 存在；非 localhost 必须是 HTTPS 且 host 与请求 Host 相同。localhost 是开发例外。读/写 buffer 均 8192，并共享 `sync.Pool` 写 buffer。证据：[`cmd/websocket.go:18`](vscode://file/D:/codes/dev_proj/libredesk/cmd/websocket.go:18:1)。
3. `go.mod` 锁定 `github.com/fasthttp/websocket v1.5.9`。本地该版本 `server_fasthttp.go:135-204` 验证 handshake 后调用 `ctx.Hijack`，创建 `Conn` 并在 hijack callback 中执行 LibreDesk handler。
4. 回调构造栈上 `ws.Client{ID, Hub, Conn, Send: make(...,128)}`，把指针加入 Hub，再显式 `go c.Listen()`，当前 callback 阻塞执行 `c.Serve()`。证据：[`cmd/websocket.go:61`](vscode://file/D:/codes/dev_proj/libredesk/cmd/websocket.go:61:1)。
5. `Listen` 设置 64 KiB read limit、60 秒 read deadline、pong handler；循环只接受 text frame。read error 或非 text frame 结束后先 `RemoveClient` 再 idempotent `close(Send)`。证据：[`internal/ws/client.go:12-18,65-86`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/client.go:12:1)。
6. `Serve` 每 25 秒写 WebSocket Ping control frame，也消费 `Send`。每次写设 10 秒 deadline；channel close、ping/write error 都退出，并 defer stop ticker + close socket。证据：[`internal/ws/client.go:40`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/client.go:40:1)。
7. 【代码分析】任一 loop 先失败最终都会驱动另一 loop 退出：read 失败会 close `Send`；writer 失败会 defer 关 socket，使 blocked read 返回，再完成 registry/subscription 清理。但 buffered channel 被 close 后，`Serve` 会先消费其中已有消息，之后才读到 `ok=false`。因此 read loop 因“收到非 text frame”等原因主动退出时，writer/socket 不保证立即退出；每次 write 各受 10 秒 deadline 约束，但源码没有整段 drain 的总 deadline。若是对端断开造成 read error，后续 write 通常也会失败；具体退出时延仍应实验确认。
8. server shutdown 先 `wsHub.CloseAll()`：发送 CloseGoingAway control、使 read deadline 立即过期、关闭 socket、remove registry、close channel；角色/用户权限或 enabled 状态变更也会通过 `KickUser` 关闭相关 agent 连接。证据：[`cmd/main.go:369`](vscode://file/D:/codes/dev_proj/libredesk/cmd/main.go:369:1)、[`internal/ws/ws.go:55-75,243-252`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/ws.go:55:1)、[`cmd/roles.go:54,108`](vscode://file/D:/codes/dev_proj/libredesk/cmd/roles.go:54:1)、[`cmd/users.go:286,337,471`](vscode://file/D:/codes/dev_proj/libredesk/cmd/users.go:286:1)。

### Widget：connect → join → cleanup

1. `GET /widget/ws` 只在 Upgrade 前通过 `rateLimit(...,"widget")`；`widgetUpgrader.CheckOrigin` 固定返回 true。证据：[`cmd/handlers.go:350`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:350:1)、[`cmd/websocket.go:44`](vscode://file/D:/codes/dev_proj/libredesk/cmd/websocket.go:44:1)。
2. Upgrade callback 设置 64 KiB read limit，创建 `safeConn`，然后在 callback 当前 goroutine 运行 JSON read loop；尚未 join 时 typing 被忽略，page visit 仅在 `userID > 0` 时处理。证据：[`cmd/widget_ws.go:113`](vscode://file/D:/codes/dev_proj/libredesk/cmd/widget_ws.go:113:1)。
3. 每轮 read 前刷新 20 秒 deadline；Widget 前端每 10 秒发应用 JSON ping，服务端回 JSON pong，并最多每秒处理一次 ping。没有 Widget 服务端主动发 WebSocket Ping 的 ticker。证据：[`cmd/widget_ws.go:31-42,137-200`](vscode://file/D:/codes/dev_proj/libredesk/cmd/widget_ws.go:31:1)、`frontend/apps/widget/src/websocket.js:238-256`。
4. join 通过全部身份/归属检查后调用 `LiveChat.AddClient(userID, disconnect)`。`disconnect` 不是直接 `Close`，而是把 socket read deadline 设置为现在，以处理 fasthttp hijacked connection 上 Close 的限制。证据：[`cmd/widget_ws.go:210`](vscode://file/D:/codes/dev_proj/libredesk/cmd/widget_ws.go:210:1)。
5. 成功 Add 后显式创建一个 forwarder goroutine：`range client.Channel` → `safeConn.WriteMessage`。随后当前 read-loop goroutine发送 `joined`。两个路径都通过 `safeConn.mu` 写。证据：[`cmd/widget_ws.go:264`](vscode://file/D:/codes/dev_proj/libredesk/cmd/widget_ws.go:264:1)。
6. 同一 socket 再次 join 时，先从旧 LiveChat registry 移除旧 client，再 `CloseChannel`，之后建立新 client/forwarder。旧 channel 已停止接收新业务消息。证据：[`cmd/widget_ws.go:152`](vscode://file/D:/codes/dev_proj/libredesk/cmd/widget_ws.go:152:1)。

   【代码分析】因为旧 channel 容量为 128，close 后旧 forwarder 会先排空已缓存 frame 才退出；新 forwarder 此时已经可能启动。二者虽然都经 `safeConn.mu`，不会并发破坏底层 writer 契约，但旧 inbox 的缓存事件可能在 re-join 后继续写入，并与新 inbox 的事件交错。这是可复现实验项，不应把 `CloseChannel` 理解为“丢弃缓冲并同步等待 goroutine 退出”。
7. read error/deadline、非活跃、显式 close 最终执行 defer：close socket；若已 join，则 `RemoveClient` 后 `CloseChannel`。forwarder 写失败时 `safeConn` 也先 close socket，使 read loop 返回并执行同一清理。证据：[`cmd/widget_ws.go:75-95,129-149,264-276`](vscode://file/D:/codes/dev_proj/libredesk/cmd/widget_ws.go:75:1)。
8. shutdown 的 `Inbox.Manager.CloseLiveChatClients` 遍历 livechat inbox 并调用 `LiveChat.Close`。后者在 `clientsMutex` 下 close 所有 channel、调用 disconnect deadline，并清空 map。证据：[`cmd/main.go:371`](vscode://file/D:/codes/dev_proj/libredesk/cmd/main.go:371:1)、[`internal/inbox/inbox.go:489`](vscode://file/D:/codes/dev_proj/libredesk/internal/inbox/inbox.go:489:1)、[`internal/inbox/channel/livechat/livechat.go:271`](vscode://file/D:/codes/dev_proj/libredesk/internal/inbox/channel/livechat/livechat.go:271:1)。

### 生命周期泄漏判断

【代码分析】正常、read error、write error、重复 join、Kick、shutdown 路径都能形成关闭闭环；这些直接路径中未发现由源码确定的永久 connection/goroutine leak。

【代码分析】以下是需要实验的潜在风险，不能直接定性为 leak：

- agent `Serve` 因写失败先退出后，依赖 `Conn.Close()` 唤醒 `Listen` 完成 registry 清理；应以断网/半开连接实验确认退出时延。
- agent `Listen` 主动结束只 close buffered `Send`，不会清空 buffer；在 socket 仍可缓慢写的情况下，资源释放时延可能是多条 write deadline 的累积，而不是固定 10 秒。
- Widget `LiveChat.Close` 在持有 `clientsMutex` 时调用每个 disconnect；当前 disconnect 只是 `SetReadDeadline`，预计很短，但未来若 callback 变为阻塞操作会扩大临界区。
- Widget forwarder 的单次写最多阻塞 10 秒；重复 join 时旧 buffer 的整体 drain 没有总 deadline，关停路径则还会使 read deadline 过期并由 read-loop defer close socket。

### 6.3 goroutine、channel 与互斥锁如何协作

### 每连接实际 loop 数量

| 连接 | LibreDesk 显式 `go` | 同一 Upgrade callback 中的 loop | 稳态与该连接关联的执行流 |
|---|---:|---:|---:|
| agent `/ws` | 1：`Listen` | 1：`Serve` | 2 个 loop；一个 reader、一个 writer+heartbeat |
| Widget，join 前 | 0 | 1：read loop | 1 个 loop |
| Widget，join 后 | 1：channel forwarder | 1：read loop | 2 个 loop；一个 reader、一个 writer |

Upgrade callback 由 fasthttp hijack 机制调度；上表只精确声称 LibreDesk 代码显式创建的 goroutine 数及 callback 内 loop 数，不把 HTTP server 内部调度 goroutine 错算成项目显式创建。

### Agent 并发控制

所有普通 data frame 和 server Ping 都在 `Client.Serve` 单一 writer loop 中直接写 `Conn`；任意业务 goroutine只调用 `trySend` 入 `Send` channel。`sendMu` 覆盖 closed 检查和非阻塞 send，也覆盖 close，解决 send/close race。证据：[`internal/ws/client.go:35-37,40-63,179-222`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/client.go:35:1)。

#### 关键代码：慢客户端不阻塞广播者

```go
c.sendMu.Lock()
defer c.sendMu.Unlock()
if c.closed {
    return false
}
select {
case c.Send <- msg:
    return true
default:
    return false
}
```

**这段代码解决什么问题：** 多个业务 goroutine 可能同时广播，而单个客户端可能已经关闭或长期不读取。

**为什么这样写：** Mutex 把“检查 closed、发送、关闭 channel”串行化，非阻塞 send 则限制慢客户端对生产者的影响；真正写 socket 仍由单写者 loop 完成。

**如果没有这段机制会怎样：** send/close 竞争可能 panic；阻塞 send 又可能让一个慢连接拖住业务广播。

**当前工程代价：** buffer 满时当前帧不会排队，调用者必须选择丢弃、记录或断开；WebSocket 本身不提供断线后的持久重放。

`closeClients` 可从 shutdown/Kick 路径调用 `Conn.WriteControl(Close)`，并可能与 `Serve.WriteMessage` 同时发生。

`fasthttp/websocket v1.5.9` 本地 `doc.go:141-153` 规定：应用必须保证普通 write 方法最多一个并发 writer；`Close` 和 `WriteControl` 可以与其他方法并发。因此 agent 的普通写符合依赖契约，close control 不破坏它。

### Widget 并发控制

Widget channel 只有 forwarder 消费；业务 producers 可并发向 channel 非阻塞发送。forwarder、read loop 的 pong/error/joined 都可能写 socket，但全部经过 `safeConn.mu`；deadline 设置与实际 write 也在同一锁内。证据：[`cmd/widget_ws.go:65-110,199,264-312`](vscode://file/D:/codes/dev_proj/libredesk/cmd/widget_ws.go:65:1)。

【代码分析】这是 mutex-serialized writers，而不是严格的单 writer goroutine：安全性满足，但 pong 与业务 frame 谁先拿锁没有语义顺序保证。

## 7. 核心链路二：业务提交后如何实时推送

以下选择“坐席通过 HTTP 给 livechat contact 回复”这一真实链，因为它同时覆盖 DB、agent WebSocket、Widget WebSocket 和异步 worker。

### HTTP 接收、落库、推 agent

```text
POST /api/v1/conversations/{cuuid}/messages
  -> cmd.handleSendMessage
  -> enforceConversationAccess
  -> conversation.Manager.QueueReply
  -> conversation.Manager.InsertMessage
       -> BEGIN
       -> SQL insert-message (status=pending)
       -> LinkMessageMediaTx
       -> COMMIT
       -> addConversationParticipant           (独立于上述事务)
       -> UpdateConversationLastMessage        (独立 SQL)
       -> GetConversationListItem
       -> BroadcastNewMessage
            -> AuthorizedConnectedAgentIDs
            -> Hub.BroadcastMessage
            -> each Client.Send -> Send chan
            -> Client.Serve -> Conn.WriteMessage
  -> HTTP response returns pending message
```

入口先做 conversation access，再调用 `QueueReply`；它构造 `pending/outgoing/agent/non-private` message。`InsertMessage` 在 transaction 内完成 message insert 与 media link，commit 后才做 conversation participant、last-message 更新和 WebSocket broadcast。证据：[`cmd/messages.go:176`](vscode://file/D:/codes/dev_proj/libredesk/cmd/messages.go:176:1)、[`internal/conversation/message.go:503-624,626-670`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:503:1)。

`insert-message` CTE 从 conversation ID/UUID 找所属会话并 insert；`conversation_messages.uuid` 有 unique constraint。消息与附件 link 同事务，但 `UpdateConversationLastMessage` 是 commit 后的独立 SQL，并且 `InsertMessage` 没有检查该调用的返回值。证据：[`internal/conversation/queries.sql:828`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:828:1)、[`schema.sql:301-324`](vscode://file/D:/codes/dev_proj/libredesk/schema.sql:301:1)、[`internal/conversation/message.go:604`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:604:1)。

【代码分析】因此已提交 message 是主事实；若后续 conversation summary 更新失败，HTTP 仍可能成功并继续广播，列表 payload 可能来自未更新/旧的 conversation list item。这不是 WebSocket 回滚能解决的问题。

`BroadcastNewMessage` 不是按 subscription map 推，而是读取当前 connected agent IDs，加载 agent 并用 `authz.CanReadAssignment` 计算接收人，再按 user ID 向其所有连接推送。payload 包含 conversation UUID、message UUID/type、preview、created_at、sender_type、conversation，以及可选 echo_id。证据：[`internal/conversation/ws.go:30`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/ws.go:30:1)、[`internal/conversation/conversation.go:2143`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/conversation.go:2143:1)。

### DB pending 扫描、推 Widget、状态回推 agent

```text
conversation.Manager.Run ticker
  -> SQL get-outgoing-pending-messages
  -> outgoingProcessingMessages.Store (进程内 sync.Map)
  -> outgoingMessageQueue
  -> MessageSenderWorker
  -> sendOutgoingMessage
       -> inboxStore.Get
       -> livechat.LiveChat.Send
            -> clients[contactID]
            -> each Client.Channel (non-blocking)
            -> widget forwarder
            -> safeConn.WriteMessage
       -> UpdateMessageStatus(sent)
            -> SQL update-message-status
            -> BroadcastMessageUpdate
            -> Hub.ListSubscribers(conversationUUID)
            -> agent Client.Send -> Serve -> socket
```

scanner 每个配置 interval 查询所有 `pending/outgoing/non-private` 且不在本进程 processing map 的消息，送入 outgoing channel；worker 调 `sendOutgoingMessage`。证据：[`internal/conversation/message.go:53-100,131-148`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:53:1)、[`internal/conversation/queries.sql:697`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:697:1)、[`config.sample.toml:98-107`](vscode://file/D:/codes/dev_proj/libredesk/config.sample.toml:98:1)。

对 livechat，`LiveChat.Send` 按 `MessageReceiverID` 找 Widget clients，构造 `new_message`，非阻塞入每个 channel；无连接返回 `ErrClientNotConnected`。`sendOutgoingMessage` 明确把该错误当作非失败，随后将 DB status 更新为 `sent`。证据：[`internal/inbox/channel/livechat/livechat.go:198`](vscode://file/D:/codes/dev_proj/libredesk/internal/inbox/channel/livechat/livechat.go:198:1)、[`internal/conversation/message.go:188`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:188:1)。

【代码分析】这里 `sent` 的语义不是“Widget 已确认收到”，甚至不严格等于“写入 socket 成功”：无在线连接、channel 满后 drop 都仍可进入 `sent`。它更接近“发送阶段没有返回需标记 failed 的 transport error”。

`UpdateMessageStatus` 先写 DB，再查询 conversation UUID 并向 list/open subscribers 发 `message_update`；广播和 webhook 错误不回滚 status。证据：[`internal/conversation/message.go:415`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:415:1)。

### Widget/外部入站消息的另一方向

Widget 发消息本身走 HTTP `POST /api/v1/widget/chat/conversations/{uuid}/message`，不是 WebSocket inbound data frame；WebSocket 只承担随后实时 fan-out。普通 contact message 经 `CreateContactMessage → InsertMessage`，commit 后 `BroadcastNewMessage` 给 agent。连续性 email 回流路径在 `ProcessIncomingMessage` insert 后额外调用 `broadcastMessageToWidgetClients`。证据：[`cmd/handlers.go:358`](vscode://file/D:/codes/dev_proj/libredesk/cmd/handlers.go:358:1)、[`internal/conversation/message.go:478-500,820-880,1431-1460`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:478:1)。

## 8. 跨链路比较：写安全、背压、顺序与恢复

### Agent

同一 agent `Conn` 的所有 Ping/data `WriteMessage` 只在 `Serve`；其他 goroutine只写 channel。`KickUser/CloseAll` 的 `WriteControl` 按第三方契约允许并发。因此普通 data frame 没有多个 goroutine 直接并发写入。

【代码分析】单 writer 同时给出每连接 FIFO（先进先出）channel 消费语义，但不等于全局业务顺序；并发 producers 谁先获得 `sendMu`、先入 channel，并无 DB 顺序约束。

### Widget

forwarder、pong、joined 和 error 都可能写同一连接，但 `safeConn.mu` 包住 deadline + write。Widget 的普通 data write 都经过 `safeConn`，没有绕过互斥锁的写入路径。

【代码分析】Widget 写安全依赖所有调用者持续使用 wrapper；`safeConn.conn` 字段是包内可见，未来新增代码绕过 wrapper 会重新引入并发写风险。

### 8.2 慢客户端与背压

| 维度 | Agent | Widget |
|---|---|---|
| 出站缓冲 | `Send`，128 | `Channel`，128 |
| 满时 | `trySend` 返回 false；普通 `SendMessage` 忽略返回，静默 drop | `select/default` drop，并写 warning |
| 队列满是否断开 | 普通业务消息不会；`SendError` 入队失败会 remove + close channel | 不会 |
| socket write deadline | 10 秒 | 10 秒 |
| writer | `Serve` 单 writer | forwarder；其他写由 mutex 串行 |

证据：[`cmd/websocket.go:66`](vscode://file/D:/codes/dev_proj/libredesk/cmd/websocket.go:66:1)、[`internal/ws/client.go:12-18,190-222`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/client.go:12:1)、[`internal/inbox/channel/livechat/livechat.go:256-265,322-326,375-387,408-418`](vscode://file/D:/codes/dev_proj/libredesk/internal/inbox/channel/livechat/livechat.go:256:1)、[`cmd/widget_ws.go:31-33,75-95`](vscode://file/D:/codes/dev_proj/libredesk/cmd/widget_ws.go:31:1)。

agent buffer 满时 `SendMessage` 不 log、不 remove、不 close；Widget 的 new message/typing/conversation update buffer 满时 log 后继续保留连接。两者都采取 drop 而不是 block。

【代码分析】写 deadline 处理的是“writer 已取到一条消息但 peer 不读导致 socket write 卡住”；buffer 满的业务消息在进入 writer 前已经丢失。慢连接最终可能因某次 socket write 超时关闭，也可能在网络仍持续缓慢可写时长期存活并间歇丢消息。

【代码分析】agent 的 `SendError` 是特殊路径：error frame 入队失败时会 remove client 并 close `Send`，但不会在该函数中 close socket。由于 closed buffered channel 仍会被 drain，它表达的是“停止接收新推送并最终结束 writer”，不是“立刻断开”。Kick/shutdown 则先直接 close socket，不受此差异影响。

【代码分析】潜在风险是 agent 的静默 drop 缺少 per-client dropped counter，单靠当前日志无法量化丢失；Widget 有 warning 但没有看到 Metrics（指标）累加。当前源码没有 WebSocket drop/queue depth 的 Metrics 或 Trace（分布式追踪）。

### 8.3 消息顺序与失败行为

### DB 与推送先后

`InsertMessage` 的 `new_message` 一定在 message/media transaction commit 之后；因此不会把尚未 commit 的 message 作为该函数正常路径事件推送。但 conversation last-message、participant、webhook 不在同一 transaction。

outgoing livechat 的 Widget 推送发生在 `UpdateMessageStatus(sent)` 之前。对在线快速 client，Widget 可能先看到 new_message，而 agent 稍后看到 status=sent。若 Widget 入队/写失败，status update 不会因此回滚。

### 顺序保证边界

单个 agent `Send` channel 和单个 Widget `Channel` 都是 FIFO；每个连接最终只有一个业务 channel consumer。

【代码分析】只可声称“已成功入同一 channel 的元素按 channel 接收顺序写出”。不能声称：

- 多个并发事务按 DB commit time 或 message ID 顺序到达；
- 不同连接看到完全相同顺序（各自可能在不同点 drop）；
- `new_message` 与来自其他 goroutine 的 `conversation_update` 有全局因果序；
- Widget 的 pong/joined 与 channel event 有业务顺序，因为它们竞争 `safeConn.mu`。

【代码分析】Widget re-join 还存在一个更具体的顺序边界：旧 closed channel 的缓存会由旧 forwarder继续 drain，新 client 的 forwarder也已可能运行；两者经同一写锁安全串行，但旧/新 inbox frame 的相对顺序由锁竞争决定。

另外，`get-outgoing-pending-messages` 没有 `ORDER BY`；即使单实例也不能由 SQL 证明 pending 消息扫描顺序。证据：[`internal/conversation/queries.sql:697`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/queries.sql:697:1)。

### 推送失败是否影响事务

所有重要推送均在相关 DB write 后调用，broadcast API 无 error 返回给业务层；channel full 也不向调用链上抛。因此推送失败不影响已提交 transaction，HTTP 也不会因普通 WebSocket drop 返回失败。

### 重连和补消息

后端 WebSocket 协议没有 sequence、offset/cursor、ACK、replay buffer 或从某位置补发的消息类型。

agent 前端重连后只重新发送当前列表 UUID 与打开会话 UUID 的 subscription；`handleOpen` 未调用消息/会话 HTTP refresh。见 `frontend/apps/main/src/websocket.js:51-69`。

Widget 前端重连后会 `joinInbox`，并执行 `syncMissedMessages`：通过 HTTP 重新 fetch conversation list 和当前 conversation，失败可重试。见 `frontend/apps/widget/src/websocket.js:71-93,283-300`。

【代码分析】所以后端自身不补 WebSocket 消息。当前 Widget UI 有 HTTP 状态再同步机制；当前 agent 重连路径没有同等的显式 missed-message sync，断线期间 gap 是否会由页面其他刷新动作偶然补齐不能当作保证。

## 9. 单进程实时模型扩到多实例会怎样

### 第一步：registry 是否只存在进程内

是。agent `Hub` 用 Go map，在每个进程启动时 `NewHub`；Widget clients 存在各进程内各 `LiveChat` instance 的 Go map。没有 DB table 保存 socket ownership，也没有 registry recovery。证据：[`cmd/main.go:249`](vscode://file/D:/codes/dev_proj/libredesk/cmd/main.go:249:1)、[`internal/ws/ws.go:15`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/ws.go:15:1)、[`internal/inbox/channel/livechat/livechat.go:148`](vscode://file/D:/codes/dev_proj/libredesk/internal/inbox/channel/livechat/livechat.go:148:1)。

### 第二步：是否有跨实例 WebSocket fan-out

【代码分析】当前 WebSocket 注册表只存在进程内，Redis 初始化与业务调用中也没有为 WebSocket 提供跨实例 Pub/Sub 或消息总线。

`go.mod` 有 Redis 客户端，但当前 WebSocket registry/broadcast 调用链不使用 Redis publish/subscribe；Redis 在本模块可见用途包括 session/cache/rate-limit/page visits，而不是 WebSocket 跨实例 fan-out。当前依赖也没有显示 NATS/Kafka/RabbitMQ client。

【代码分析】审慎结论：当前源码没有显示存在 Redis、DB notification 或 message bus 驱动的跨实例 WebSocket fan-out。

### 第三步：水平扩展行为

【代码分析】若业务写请求在实例 A，而目标 WebSocket 只连接实例 B：

- A 的 `Hub.ConnectedUserIDs` 看不到 B 的 agent，因此不会向该 agent 连接推送；
- A 的 `LiveChat.clients` 看不到 B 的 Widget，因此 `LiveChat.Send` 可能返回 `ErrClientNotConnected`，但消息仍被标为 sent；
- sticky session（会话粘滞）只能提高同一用户请求与连接同实例的概率，不能自然覆盖后台 worker、Webhook/email 入站或跨用户 fan-out。

【代码分析】另外 pending scanner 与 `outgoingProcessingMessages` 都是进程内；多实例可同时读取同一 pending row。这个问题属于消息发送 worker 的跨实例 claim 机制，直接影响“业务事件进入 WebSocket”的 livechat 路径，但需要单独实验验证重复处理，不能仅凭两个实例就声称必然每次重复。

【设计建议】若明确要求多实例实时一致性，可在 DB commit 后写 outbox（事务外发箱）事件，由跨实例 broker 分发到各实例本地 registry；事件带 conversation/message ID 与单调序号，客户端按 ID 去重并在 gap 时 HTTP sync。是否采用 Redis Streams、PostgreSQL LISTEN/NOTIFY 或专用 broker 应由吞吐、保留、重放和运维要求决定，当前源码没有给出选择依据。

## 10. 已确认的工程限制与待实验验证

### 当前验证状态

| 实验 | 当前状态 | 能得到的结论 |
|---|---|---|
| `internal/ws` 与 Conversation 广播模型测试 | 已通过 | Client 删除和广播 DTO 字段隔离已有基础覆盖 |
| Race Detector（数据竞争检测器） | 工具链未能构建 | 没有获得 race-clean 证据，也不能据此判定源码存在数据竞争 |
| 真实 handshake、heartbeat、慢客户端与断线 | 未执行 | 有界队列、drop 和清理语义仍需协议级实验 |
| 双实例 fan-out | 未执行 | 当前跨实例广播结论仍来自进程内 registry 的源码边界 |

### 最小慢客户端实验

目标：验证 128 buffer、drop 与最终断开，不做完整 benchmark。

1. 用 `websocket.Dialer` 建 agent 连接，完成认证和 subscription，但暂停读取 server frame。
2. 在同进程对该 conversation 连续触发 150～300 条可识别序号的 `conversation_update`。
3. 记录 client 实际收到序号、server registry 是否仍保留连接、10 秒后是否因某次 write timeout 被移除。
4. agent 与 Widget 各做一次；Widget 同时断言日志出现 `client channel full, dropping...`。

验收指标：成功入队数、drop 数（需测试 hook 或临时 counter）、首次 gap、连接移除时延、goroutine 前后差值。

Widget 追加一个 re-join 子用例：先阻塞 writer 并填充旧 client channel，再在同一 socket join 另一个 inbox；恢复读取后检查是否出现旧 inbox 缓存 frame 与新 inbox frame 交错。

### 最小顺序实验

1. 两个 goroutine并发提交同一 conversation 的带 `producer/seq` 消息。
2. 同时记录 DB `id, created_at`、agent frame 顺序、Widget frame 顺序。
3. 重复 100 次，但不以吞吐作为 benchmark 结论。

要验证的不是“WebSocket 是否 FIFO”，而是 producer 入 channel 顺序与 DB 顺序是否可能不同，以及不同连接 drop 后是否形成不同序列。

### 生命周期与 goroutine leak 实验

1. 记录 `runtime.NumGoroutine()` / pprof goroutine profile 基线。
2. 创建并关闭 100 次 agent 和 Widget 连接；覆盖正常 close、read timeout、server Kick、写端不读、Widget re-join。
3. 等待至少 `writeWait`/`wsWriteDeadline` 加调度余量后再次采样。
4. 检查 Hub/LiveChat registry 长度归零，并比较残留 stack 是否停在 `Listen`、`Serve` 或 `range client.Channel`。

### 最小双实例实验

1. A/B 连接同一 PostgreSQL/Redis，监听不同端口；不配置 sticky routing。
2. Widget 只连 B；向 A 发坐席回复 HTTP 请求，并确认由 A worker 处理。
3. 检查 DB message status、B Widget 是否收到、A/B 日志与各自 registry。
4. agent 只连 B，再由 A 产生 incoming message，重复验证。

预期必须由实验确认；从进程内 registry 可以推导 B 不会收到 A 的本地 broadcast，但不能把推导写成【实验结果】。

### Race Detector 工具链恢复后

先确认 `go env GOOS GOARCH CGO_ENABLED` 和 C compiler，再执行：

```powershell
go test -race -count=20 ./internal/ws ./internal/conversation
```

建议新增并发测试覆盖：`BroadcastMessage ↔ Listen cleanup`、`KickUser ↔ SendMessage`、`LiveChat.Send ↔ RemoveClient/Close`、重复 join 与 shutdown。

## 11. 面试表达

> LibreDesk 把 PostgreSQL 当作业务事实源，把 WebSocket 当作实时通知通道。Agent 连接通过 Client 的发送 channel 和单写 goroutine 串行写帧，Widget 则由 `safeConn` 的 mutex 保护写操作。Hub 维护当前进程的连接与 Conversation 订阅，并在业务提交后按订阅范围扇出。这样能快速推送，但事件本身没有持久化重放，多实例之间也没有共享 fan-out，所以客户端断线后必须依靠 HTTP 和数据库恢复状态。

## 本章必须记住的源码锚点

### [`Hub`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/ws.go:15:1)
**为什么必须记住：** Agent 连接与订阅关系的进程内事实源。  
**面试关联：** 多实例时为什么看不到其他实例的连接？

### [`Client`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/client.go:22:1)
**为什么必须记住：** 每条连接的读写 goroutine 和发送队列。  
**面试关联：** 为什么 WebSocket 常采用单写者？

### [`BroadcastMessage`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/ws.go:209:1)
**为什么必须记住：** 订阅过滤与扇出的核心。  
**面试关联：** 广播授权依赖哪些 Conversation 数据？

### [`Client.SendMessage`](vscode://file/D:/codes/dev_proj/libredesk/internal/ws/client.go:221:1)
**为什么必须记住：** Agent 慢客户端的队列与过载策略。  
**面试关联：** 队列满时系统选择阻塞、丢弃还是断开？

### [`safeConn.WriteMessage`](vscode://file/D:/codes/dev_proj/libredesk/cmd/widget_ws.go:87:1)
**为什么必须记住：** Widget 多来源写帧的 Mutex 串行化边界。  
**面试关联：** Mutex 与单写者 goroutine 分别怎样保证写安全？

### [`UpdateMessageStatus`](vscode://file/D:/codes/dev_proj/libredesk/internal/conversation/message.go:416:1)
**为什么必须记住：** DB 状态提交后再广播的典型边界。  
**面试关联：** 实时通知失败为什么不回滚 Message 状态？

## 12. 面试追问

1. 为什么同一 WebSocket 连接需要 single writer？
2. Agent channel 与 Widget mutex 两种写模型有什么差异？
3. 慢客户端如何把压力传回发送方？
4. DB commit 成功但 WebSocket push 失败时，客户端如何恢复？
5. 多实例部署为什么需要跨实例 pub/sub 或其他 fan-out 层？
