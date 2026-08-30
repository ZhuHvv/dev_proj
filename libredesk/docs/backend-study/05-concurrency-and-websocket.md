# Day 5：并发、WebSocket（全双工长连接协议）与可靠性

## 1. 先建立 Go 并发组件地图

项目中常见的并发原语：

| 原语 | 用途 | 例子 |
|---|---|---|
| `context.Context`（上下文） | 传递取消信号和超时 | main、Worker（工作协程）、AI 请求 |
| `chan`（通道） | 任务队列或连接发送队列 | Message、Automation、Webhook、WebSocket Client |
| `sync.WaitGroup`（等待组） | 等待 Worker 结束 | Manager.Close |
| `sync.RWMutex`（读写互斥锁） | 保护共享 map/config | WebSocket Hub、Inbox Clients、AI Index |
| `sync.Map`（并发映射） | 处理中的消息 ID | outgoing processing set |
| `atomic.Value` / `atomic.Uint64`（原子变量） | 读多写少状态、代次 | App constants、AI reindex generation |
| Ticker（周期触发器） | 周期扫描 | pending message、SLA（服务等级协议）、清理任务 |

学习并发不能只判断“有没有锁”，还要回答：锁保护哪条不变量、channel 是否会满、关闭时是否会 send-on-closed-channel、多个实例是否共享状态。

## 2. Agent（客服坐席）WebSocket 的结构

[`Hub`](../../internal/ws/ws.go#L15-L39)（连接与订阅中枢）维护：

- `clients`: user ID 到多个 Client 的映射。
- 会话列表订阅。
- 当前打开会话订阅。
- Client 到订阅的反向映射，便于断线清理。

一个 Agent 可以同时打开多个浏览器标签，因此一个 user ID 对应 `[]*Client`，而不是单连接。

[`cmd/websocket.go`](../../cmd/websocket.go) 完成协议升级。Agent WebSocket 要求 HTTPS 同源，开发时放行 localhost。升级成功后：

```text
Hub.AddClient
  -> goroutine: Client.Listen 负责读
  -> 当前 goroutine: Client.Serve 负责写和心跳
```

同一 WebSocket 连接由单独的读循环和写循环管理，这是常见做法。大多数 WebSocket 库不允许多个 goroutine 无序并发写。

具体入口是 [`Client.Listen`](../../internal/ws/client.go#L66-L88) 和 [`Client.Serve`](../../internal/ws/client.go#L41-L63)。断线调试时要观察哪条路径先返回、谁调用 `RemoveClient`，以及底层 Conn 和 Send channel 是否重复关闭。

## 3. 心跳与连接清理

[`internal/ws/client.go`](../../internal/ws/client.go) 设置：

- Pong 等待时间 60 秒。
- 每 25 秒发送 Ping。
- 写超时 10 秒。
- 单帧最大 64 KiB。
- 一次列表订阅最多 500 个 UUID。

心跳的作用不是业务保活，而是及时发现网络已经断开但 TCP（传输控制协议）尚未报告的半开连接。

断线时必须同时：

1. 从 `clients` 删除 Client。
2. 清理其列表和打开会话订阅。
3. 关闭发送 channel。
4. 关闭底层连接。

`Client.close` 使用 mutex（互斥锁）+ `closed` 标记，使关闭幂等（重复调用结果与调用一次相同），避免多个读写路径重复 close channel。

Hub 同时维护 `conversation -> clients` 与 `client -> conversations` 两套索引。前者让广播快速，后者让断线清理不必扫描全部会话；列表订阅和打开会话订阅又分别保存在 [`SubscribeListReplace`](../../internal/ws/ws.go#L79-L97) 与 [`SubscribeOpenConv`](../../internal/ws/ws.go#L99-L113) 对应的 map 中。更新必须在同一 `subsMu` 临界区维护双向关系，否则会产生幽灵订阅或内存泄漏。

## 4. 慢客户端与背压（下游处理变慢时限制上游生产速度）

每个 Client 的 `Send` 是大小 128 的缓冲 channel。`trySend` 使用非阻塞 `select`：

```go
select {
case c.Send <- msg:
    return true
default:
    return false
}
```

这意味着广播方不会被一个不读数据的浏览器永久拖住。缓冲区满时普通消息会被丢弃；错误消息入队失败时连接会被关闭。

这是明确的可用性权衡：

- 保住整个 Hub，不让慢客户端制造全局阻塞。
- 允许个别实时事件丢失。
- 前端必须能通过 HTTP 重新拉取事实状态，不能依赖收到每一帧。

这段行为可以直接对照 [`Client.trySend`](../../internal/ws/client.go#L190-L202)、[`SendError`](../../internal/ws/client.go#L204-L217) 和 [`SendMessage`](../../internal/ws/client.go#L219-L222)。建立连接后暂停读取，连续制造超过 128 条广播，再用 HTTP 拉取 Conversation：实验应同时证明慢客户端不阻塞 Hub、实时帧丢失后业务状态仍可恢复。

## 5. 订阅授权

Client 支持两类会话订阅：

- 列表订阅：替换当前列表 UUID 集合。
- 打开会话订阅：保持当前详情页 UUID。

订阅前调用 `FilterAuthorizedListUUIDs`，只留下该 Agent 有权限读取的 Conversation。否则攻击者可直接发送任意 UUID 订阅消息，绕过 HTTP 权限获取后续推送。

对应代码位于 [`handleListSubscribe`](../../internal/ws/client.go#L115-L136)、[`handleConversationSubscribe`](../../internal/ws/client.go#L138-L156) 和 [`FilterAuthorizedListUUIDs`](../../internal/conversation/conversation.go#L2164-L2189)。可发送一组有权/无权 UUID，断点观察过滤结果；typing 不走同样查询，是源码明确接受的装饰性信号权衡。

Typing 是一个被明确接受的例外：源码注释说明它是短暂、装饰性数据，因此没有为每一帧增加数据库授权成本。面试时应说明这是威胁模型下的权衡，不是“Typing 不需要安全”。

## 6. Widget WebSocket 为什么单独实现

[`cmd/widget_ws.go`](../../cmd/widget_ws.go) 与 Agent Socket 不同：

- Widget 天生跨域，Origin 不能要求和客服后台同源。
- 通过 Widget Session Token 和 Inbox ID 验证访客身份。
- Join 后再次确认 Session 属于该 Inbox、User 存在且启用。
- 对 typing、page_visit、ping 帧分别限速。
- 对所有写操作用 `safeConn.mu` 串行化。
- 设置读写 deadline 和单帧大小。

“跨域 WebSocket 允许所有 Origin”并不自动等于漏洞，但认证 Token 必须足够强、作用域明确、有效期受控，并防止被不可信页面窃取。

## 7. 进程内安全不等于分布式安全

### Pending Message

`outgoingProcessingMessages sync.Map` 只能阻止当前进程把同一 ID 重复放进队列。如果启动两个 App 实例，它们都可能查询到同一 pending 行。

常见改造方案：

```sql
BEGIN;
SELECT id
FROM conversation_messages
WHERE status = 'pending'
FOR UPDATE SKIP LOCKED
LIMIT ?;

UPDATE ... SET status = 'processing', lease_until = ...;
COMMIT;
```

还需要租约超时，让崩溃实例留下的 processing 任务能够恢复。

不能只改 SQL：当前 scanner 把批量结果同步写入 channel，`Close()` 又直接关闭 channel，而 scanner goroutine 没有被 `WaitGroup` 跟踪。多实例改造时应同时重构生产者生命周期：停止 claim、新任务不再入队、允许或限时排空、最后关闭消费者，且所有阻塞发送都能响应 context。

### Automation/Webhook

它们的 task queue 也位于单进程内。队列满时部分模块采用 drop + log；进程崩溃时未落库任务可能丢失。要不要持久化取决于业务是否允许丢事件。

还要检查 `Close()` 的锁顺序。Automation/Webhook/Notification 的关闭函数在持有“禁止生产”锁时等待 Worker；如果 Worker 的业务回调再次尝试入队并获取同一把读锁，就可能形成关闭死锁。是否真实可达要用调用图和关停并发测试证明，但不能忽略。

### WebSocket

Hub 的连接表是进程内状态。多实例下，HTTP 更新可能发生在 A 实例，而目标 Agent 连接在 B 实例。需要 Redis Pub/Sub（发布/订阅）、NATS（消息通信系统）等跨实例广播层，或负载均衡粘性连接加事件转发。

## 8. 五类故障语义

分析任何异步模块时都检查：

| 故障 | 当前可能结果 | 常用改进 |
|---|---|---|
| 队列满 | 丢弃、阻塞或返回错误 | 限流、扩容、持久队列、监控 |
| Worker panic | goroutine 退出甚至进程崩溃 | recover 边界、Supervisor、测试 |
| 外部超时 | Worker 被占用 | deadline、熔断、隔离池 |
| 进程重启 | 内存任务丢失 | DB（数据库）/MQ（消息队列）持久化、重放 |
| 重复执行 | 重复邮件/动作 | 幂等键、唯一约束、去重表 |

## 9. `Close()` 审查清单

看到“关闭 channel + WaitGroup”时检查：

1. 是否先阻止新生产者？
2. 是否可能有人仍向已关闭 channel 发送？
3. Worker 在 `ctx.Done()` 与 channel 数据同时就绪时会选择哪个？
4. 是排空队列还是立即停止？
5. 锁是否在 `Wait()` 期间持有，造成其他 goroutine 无法退出？
6. `Close()` 是否幂等？

这些问题比背诵 Mutex 和 Channel 的定义更接近真实后端面试。

## 10. 当天实践

1. 打开两个浏览器标签，验证同一 Agent 的多连接行为。
2. 让一个 WebSocket 客户端停止读取，推演其 Send 缓冲区满后的结果。
3. 追踪 Subscribe、Broadcast、RemoveClient 的锁顺序。
4. 使用 `go test -race` 运行 `internal/ws` 测试。
5. 写出单实例 pending 扫描改为多实例安全租约的伪代码。
6. 写一个 shutdown 压测：填满各 channel、让外部调用变慢、发送 SIGTERM，验证无 panic、无死锁并记录实际丢弃范围。

## 11. 面试表达

> 实时层使用进程内 Hub 管理用户多连接和会话订阅，读写循环分离，通过 Ping/Pong、Deadline、帧大小限制和非阻塞发送处理失活及慢客户端。订阅前批量执行资源授权，普通实时帧允许在背压下丢弃，由 HTTP 数据源负责恢复。当前 Hub 和 pending 去重都是进程内语义；若做多实例部署，需要数据库抢占/租约和跨实例 Pub/Sub。
