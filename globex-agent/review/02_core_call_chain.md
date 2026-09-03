# 02 一次用户请求的完整调用链追踪

> 主线选择当前前端使用的 `POST /commerce/intents`。队列关闭时由 API（Application Programming Interface，应用程序编程接口）进程执行；队列开启时由 API 入队、worker 执行。请求成功进入 Agent 执行阶段后，两条路径都会进入 `MainAgentOrchestrator.handle_intent()`。
>
> Agent 内部不是固定业务流水线。本文先写代码确定的外层骨架，再写模型运行时可能选择的工具分支。

## 1. 入口与响应通道

### 1.1 前端

[App.tsx](../frontend/src/App.tsx#L22) 从 `localStorage` 读取或创建 `sessionId` 和 `buyerId`，随后并行使用两条通道：

- HTTP（Hypertext Transfer Protocol，超文本传输协议）：`submit()` 向 `POST /commerce/intents` 提交 session、buyer、locale、currency 和 `raw_query`。
- WebSocket：组件 `useEffect()` 连接 `/commerce/events`，连接成功后先发送同一个 `shopping_session_id` 作为订阅条件。

当前前端会等待 `fetch()` 完成，但不解析 HTTP JSON。聊天文本实际来自 WebSocket：

- `token.delta`：追加到临时流式气泡。
- `final.result`：清空临时气泡并加入最终 Agent turn。
- 其他事件：加入时间线；最近一条带 `hits` 的 `tool.result` 用于商品卡。

这形成了一个明确的可用性边界：提交按钮不要求 WebSocket 已连接，`fetch()` 也不检查 `response.ok`。如果首次 WebSocket 尚未建立、连接中途断开或 `final.result` 转发失败，即使 HTTP 已成功返回 `final_text`，前端也不会把它加入聊天区；WebSocket 重连只接收新事件，不会补拉历史结果，见 [App.tsx](../frontend/src/App.tsx#L79) 和 [eventbus.py](../app/infrastructure/eventbus.py#L90)。

前端派生状态还有两个容易误读的边界：

- `ProductCards.latestCards()` 会从全部历史事件中倒序寻找最近一条 **非空** `hits`。新一轮零命中、语义缓存命中、直接回答或报错时都没有新的非空 hits，旧商品卡仍会显示；并行子 Agent 产生多条搜索结果时，最后到达的工具事件决定卡片，而不是 MainAgent 最终文本中采用的候选。卡片因此是原始工具结果的视图，不是最终推荐清单，见 [ProductCards.tsx](../frontend/src/components/ProductCards.tsx#L4)。
- `streaming` 只在收到 `final.result` 时清空。若已经收到部分 `token.delta` 后只收到 `error`，临时气泡不会自动结束或清除，见 [App.tsx](../frontend/src/App.tsx#L57)。
- 后端会发布 `cache.hit`、`task.queued`、`task.started`，但前端 `TradeEventType` 联合类型和事件标签表没有声明这些类型。JSON 运行时仍会进入默认展示分支，但 TypeScript 契约、样式和专用摘要已经与后端事件枚举漂移，见 [types.ts](../frontend/src/types.ts#L3)、[EventTimeline.tsx](../frontend/src/components/EventTimeline.tsx#L3) 和 [eventbus.py](../app/infrastructure/eventbus.py#L30)。

### 1.2 FastAPI

应用在 [server.py](../app/presentation/server.py#L54) 的 `build_app()` 中创建。lifespan 启动时构建 `Container`、执行 `startup()`，并在启用 Redis 背板时启动远端事件转发协程；关闭时取消该协程并释放容器资源。

lifespan 不是最早的失败边界：`build_app()` 会在应用构造期通过 `build_container_origins()` 调用 `load_settings()`，缺少必填配置时可在 lifespan 前直接失败。进入 lifespan 后，`build_container()` 对 tracing、Qdrant/KnowledgeBase 和数据库 engine 的构造也没有统一兜底；只有各 bootstrap 实际捕获的初始化异常会按对应策略记录告警或降级。CORS（Cross-Origin Resource Sharing，跨源资源共享）配置读取位置见 [server.py](../app/presentation/server.py#L89)，容器构造见 [composition.py](../app/composition.py#L129)。

核心请求 DTO（Data Transfer Object，数据传输对象）定义于 [dto.py](../app/presentation/dto.py#L13)：

```python
class SubmitIntentRequest(BaseModel):
    shopping_session_id: Optional[str] = None
    buyer_id: str = Field(min_length=1)
    locale: str = "zh-CN"
    currency: str = "CNY"
    raw_query: str = Field(min_length=1)
```

`submit_intent()` 将 DTO 转为 `SubmitIntentInput`；未传 session 时生成 `session-{8位十六进制}`。之后仅按 `Container.task_queue` 是否存在分叉。

## 2. 两种执行模式

### 2.1 队列关闭：API 进程直跑

```text
App.submit()
→ POST /commerce/intents
→ server.submit_intent()
→ SubmitIntentRequest → SubmitIntentInput
→ orchestrator.handle_intent()
→ SubmitIntentOutput
→ SubmitIntentResponse
```

队列未配置不影响 Agent 逻辑，只是 Orchestrator 在 API 进程中运行。

### 2.2 队列开启：API 入队，worker 执行

队列只有同时满足 `REDIS_URL` 非空且 `QUEUE_ENABLED` 开启时才创建，见 [composition.py](../app/composition.py#L156)。

API 侧：

```text
server.submit_intent()
→ _enqueue()
   ├─ sha256(session_id + raw_query) 生成幂等指纹
   ├─ Redis SET NX idem key，TTL（Time To Live，生存时间）600 秒
   ├─ 按会话轮数选择 normal / large Stream
   ├─ XADD IntentTask
   ├─ 写 TaskStatus=queued，TTL 3600 秒
   └─ 发布 task.queued
→ _await_result()
   ├─ 订阅本 session 的 EventBus
   ├─ 收到本 session 的 final.result 时返回（事件不含 task_id）
   ├─ 每 2 秒超时后查询 done / failed 状态
   └─ 超过 QUEUE_WAIT_SECONDS 时返回固定超时文本
```

worker 侧：

```text
app.worker.main()
→ build_container() + startup()
→ RedisStreamTaskQueue.consume()
→ handle(IntentTask)
   ├─ TaskStatus=running
   ├─ 发布 task.started
   ├─ orchestrator.handle_intent()
   └─ TaskStatus=done + final_text，或 failed + error
→ handler 正常返回后 XACK
```

worker 事件先在 worker 的 EventBus 发布，再经 Redis Pub/Sub（发布/订阅）背板到 API 进程，由 `_forward_remote_events()` 调用 `deliver_local()`，最终到达 `_await_result()` 和 WebSocket 订阅者。

### 2.3 队列边界

- 幂等键在 `XADD` 之前写入；若后续入队失败，键可能暂时指向没有任务状态的 task ID，直到 10 分钟 TTL 到期。
- `XADD`、写 `TaskStatus=queued` 和发布 `task.queued` 也不是原子操作：消息可能已经进入 Stream，但状态写入或事件发布失败。更隐蔽的竞态是 worker 可在 `XADD` 后立即消费，把状态写成 `running` 甚至 `done`，随后 API 再无条件覆盖为 `queued`。这不仅会造成短暂查不到状态，还可能让已完成任务长期倒退并停留在 `queued`，同步等待方因而超时，见 [server.py](../app/presentation/server.py#L242) 和 [worker.py](../app/worker.py#L51)。
- `consume()` 以全局 `free_slots` 作为 `XREADGROUP count`，但一次调用同时读取 normal 与 large 两条 Stream。Redis 的 `COUNT` 是每条 Stream 的最大返回数，不是所有 Stream 合计上限，因此两条流都有消息时，一轮最多创建 `2 × free_slots` 个任务，实际在途数可能超过 `WORKER_CONCURRENCY`；把 normal 放在参数前只影响返回顺序，不构成严格的累计优先配额，见 [redis_stream_queue.py](../app/infrastructure/queue/redis_stream_queue.py#L119) 和 [Redis XREADGROUP 文档](https://redis.io/docs/latest/commands/xreadgroup/)。
- 该幂等键只覆盖“提交端去重”，不是端到端业务幂等：指纹由 `session_id + raw_query` 组成，不含 buyer；worker 执行前也不检查 task 是否已完成，task ID 更没有传给订单 UseCase。若未来接通 pending 重领或出现重复消费，订单写操作仍可能再次执行。
- `_await_result()` 在 `_enqueue()` 之后才订阅事件，可能错过极快完成的 `final.result`；每两秒查询 task status 是兜底。
- `_await_result()` 的实时事件分支只按 `shopping_session_id` 订阅，收到 `final.result` 后没有核对 `task_id`，而该事件载荷本身也不含 `task_id`。同一 session 并发提交多个同步请求时，多个等待者可能都返回最先完成的那条结果；按 task ID 查询状态的兜底只有在两秒内没有收到事件时才执行。
- `claim_stale()` 使用 `XAUTOCLAIM`，但当前没有被 `consume()` 或 worker 调用。它还只处理普通 `_STREAM`，没有处理 `_LARGE_STREAM`，并且只返回反序列化后的 `IntentTask`，没有保留原始 stream 与 message ID，调用方无法在处理后准确 ack。pending 消息会留在 Redis，却不会由现有主链自动重新处理；仅增加一个调用点也不足以闭合恢复流程，见 [redis_stream_queue.py](../app/infrastructure/queue/redis_stream_queue.py#L198)。
- 成功消息和死信消息目前只 `XACK`，没有 `XDEL` 或 `XTRIM`；normal、large、dead 三条 Stream 的历史条目都可能持续增长。`XACK` 只移除消费者组 pending 状态，不会删除 Stream 条目，见 [redis_stream_queue.py](../app/infrastructure/queue/redis_stream_queue.py#L166)。
- Redis Pub/Sub 不持久化事件，WebSocket 断线期间没有事件重放。

## 3. Orchestrator 固定主链

核心入口是 [MainAgentOrchestrator.handle_intent()](../app/application/agents/orchestrator.py#L140)。

### Step 1：建立请求级上下文

构造 `ShoppingContextSnapshot(session, buyer, locale, currency)` 并写入 `ContextVar`。深层工具据此读取当前请求携带的 session 和 buyer，而不是让模型提供身份参数；但这两个值仍由客户端提交，当前代码没有认证、签名或 session 与 buyer 的绑定校验，不能把它们当成已经验证的真实身份。

`locale` 和 `currency` 虽然也进入 Snapshot，却没有形成确定性的业务约束：本轮模型输入不包含这两个字段，商品工具也不会从 Snapshot 自动取币种，而是由模型显式传 `target_currency`，未传时默认 `CNY`。SQL（Structured Query Language，结构化查询语言）中已存在的 conversation session 再次触达时只更新 `last_active_at`，不会刷新原来的 buyer、locale、currency。因此它们目前主要是请求与审计元数据，不能据此断言回复语言或价格币种一定遵循请求值，见 [orchestrator.py](../app/application/agents/orchestrator.py#L411)、[product_search_tool.py](../app/application/tools/product_search_tool.py#L24) 和 [repositories.py](../app/infrastructure/persistence/sql/repositories.py#L111)。

`init_budget(TOKEN_BUDGET_TOTAL)` 同时初始化可选的请求级 token 账本。若开启 drift detector（漂移检测），则记录本轮 query；若存在 `ConversationStore`，还会为本轮事件轨迹建立独立 EventBus 订阅。

### Step 2：获取或恢复 MainAgent

`SessionRegistry.get_or_create(session_id)` 的顺序是：

```text
进程内 _agents 已有实例 → 直接复用
否则 SessionStore.load(session_id)
  ├─ 合法 JSON → AgentState.model_validate_json(raw)
  └─ 无数据或恢复失败 → restored_state=None
→ MainAgentFactory.build(restored_state)
```

恢复失败只记录 warning，并按新会话继续。`SessionRegistry._agents` 当前没有淘汰策略，也没有同 session 并发锁。两个请求首次并发访问同一 session 时还可能分别构建 Agent，随后互相覆盖 `_agents` 条目；已存在实例时则可能并发操作同一个 AgentState。

队列模式还存在跨进程版本：每个 worker 都有独立的 `SessionRegistry`，Redis Stream 不按 session 绑定消费者，也不阻止同 session 的多个任务并发执行。两个 worker 可能读取同一份旧 SessionStore 快照、各自在不同 AgentState 上推进，最后通过 `SqlSessionStore.save()` 覆盖写；当前没有版本号、CAS（Compare-And-Set，比较并交换）、分布式 session 锁或会话级串行队列防止上下文分叉和最后写入覆盖，见 [worker.py](../app/worker.py#L82)、[main_agent.py](../app/application/agents/main_agent.py#L171) 和 [repositories.py](../app/infrastructure/persistence/sql/repositories.py#L96)。

`AgentState.permission_context` 中还会写入项目级 allow 规则，直接放行下单、取消、调度、偏好和 Task 工具。对 Agent 工具路径而言，下单/取消前“先展示确认卡并等待用户明确确认”目前只是 [globex.yml](../app/application/prompts/globex.yml#L59) 中的 Prompt 约束，没有后端确认令牌或状态机做硬校验。直连的 `POST /commerce/orders/{order_id}/cancel` 不经过 Agent 或 Prompt，会直接调用取消 UseCase。

### Step 3：尝试语义缓存短路

只有同时满足以下条件才会查 Redis `SemanticCache`：

- Redis 缓存和语义缓存开关已启用。
- MainAgent 当前没有历史 `state.context`；这只是代码判据，不一定等于业务上的第一轮。
- query 不命中下单、取消、订单引用或“刚才/这个”等固定正则拒绝规则。

缓存 key 按模型与 Prompt 指纹、buyer ID、全量偏好指纹分桶。命中时 `_lookup_cache()` 先发布 `cache.hit`，返回缓存文本后再进行输出审核并发布 `final.result`，不进入 `agent.reply_stream()`；`finally` 中仍会尝试持久化状态和本轮对话。

这里的“可缓存”是启发式判断，不是对只读语义的完备识别。规则主要列举中文关键词；例如未命中的中文近义说法或英文写操作表达仍可能进入缓存，所以不能概括为“写操作一定不缓存”。分桶也没有包含 `locale`、`currency`、工具可用性，以及商品、库存、汇率、关税、知识库等业务数据版本；同一 buyer 与偏好指纹下，缓存回复可能沿用旧语言、旧币种或旧业务数据，见 [semantic_cache.py](../app/infrastructure/cache/semantic_cache.py#L41) 和 [semantic_cache.py](../app/infrastructure/cache/semantic_cache.py#L101)。

需要注意：缓存命中没有把 buyer query 或缓存回复追加到 AgentState，持久化的是未变化的状态。下一轮若询问“刚才那个”，正则规则会禁止再次命中缓存，但 Agent 也没有上一轮缓存回复可供引用。对话流水虽然保存了这两条记录，`SessionRegistry` 恢复 Agent 时却只加载 `SessionStore` 中的 AgentState，不会从 `ConversationStore` 回放对话。缓存路径也不会重放商品搜索的 `tool.result`，因此前端可能继续展示上一轮商品卡。

### Step 4：构造本轮输入

固定输入是 `UserMsg(intent.buyer_id, intent.raw_query)`。Orchestrator 读取买家偏好，经 `PreferenceSelector` 筛选后可在其前面加入：

```text
UserMsg("memory_hint", "<buyer-preferences>...</buyer-preferences>")
```

所有 `dislike` 都按存储顺序保留；`like` 最多 top-k。默认先按 `created_at` 倒序选出最新项，开启相关性配置后按 embedding 相似度选出相关项，最终都恢复入选项在原列表中的相对顺序。在同一个 Orchestrator 进程实例的生命周期内，同一 session 已注入且渲染结果未变化时，不重复注入偏好消息；该去重快照只存在进程内，服务重启并恢复 AgentState 后仍可能再次注入相同偏好。

“所有 dislike 都注入”不等于后端进行了偏好硬过滤。`ProductSearchSpec` 的结构化硬条件只有 `ship_to`、`price_max_major` 等字段，没有材质、品牌或任意偏好排除字段；偏好是否被执行依赖模型遵循 Prompt。并且 `product_search_tool` 会在 MainAgent 二次筛选前把原始 hits 发布给前端，所以最终文字即使排除了某商品，卡片仍可能展示它，见 [catalog_search.py](../app/application/usecases/catalog_search.py#L129) 和 [product_search_tool.py](../app/application/tools/product_search_tool.py#L94)。

“不再注入”不等于“从 AgentState 撤回”。`forget_preference_tool` 只删除 Store 中的偏好，不会扫描或删除 AgentState 中已经追加的旧 `<buyer-preferences>` 消息；因此旧 hint 在上下文被压缩或淘汰前仍可能影响模型。偏好清空时 `_injected_preferences` 也不会清除，之后重新创建完全相同的偏好时，当前进程内可能被误判为已经注入，见 [forget_preference_tool.py](../app/application/tools/forget_preference_tool.py#L43) 和 [orchestrator.py](../app/application/agents/orchestrator.py#L411)。

### Step 5：进入 AgentScope reply loop

项目调用边界是 [orchestrator.py](../app/application/agents/orchestrator.py#L333)：

```python
async for event in agent.reply_stream(inputs or None, yield_final_msg=True):
    if isinstance(event, Msg):
        final_text = event.get_text_content() or ""
    elif isinstance(event, TextBlockDeltaEvent):
        self._bus.publish(session_id, "token.delta", ...)
```

`token.delta` 在流式生成时立即发布，而 `_guard_final_text()` 要等 reply loop 结束、拿到完整文本后才执行。因此最终文本中的脱敏不能撤回已通过 WebSocket 发出的原始 token；内部工具名、密钥形态或内部 URL 仍可能先出现在临时气泡中。`token.delta` 又被轮末对话事件持久化明确排除，事后审计也不会保留这段原始流，见 [orchestrator.py](../app/application/agents/orchestrator.py#L264) 和 [orchestrator.py](../app/application/agents/orchestrator.py#L333)。

本项目还将四个 Task 工具的结果映射为 `plan.update`，并把工具结果摘要交给可选漂移检测器。业务工具的 `tool.invoke` / `tool.result` 和 `agent.dispatch` 由工具自身发布。

AgentScope 如何把消息转换为某次具体 tool call 属于依赖库内部行为；当前仓库只能确认注册的工具、Prompt 约束和实际执行函数，不能从静态代码断言某句话必然调用哪个工具。

### Step 6：调用 Chat Model

MainAgent、SearchAgent、TradeAgent 都通过 [llm.py](../app/infrastructure/llm.py#L217) 的 `create_chat_model()` 创建模型。`ThrottledChatModel.__call__()` 的外层行为为：

1. 获取同一 `Container`、同一进程内共享的 `GatewayThrottle` 名额，限制并发数和相邻请求起跑间隔。每个 API/worker 进程各自构造一份 throttle，多 worker 部署的集群总并发近似为各进程限额之和，不是分布式全局限额，见 [composition.py](../app/composition.py#L197)。
2. 调 AgentScope `OpenAIChatModel`；流式响应读完或关闭后才释放名额。
3. 在上游响应流创建完成之前遇到瞬时错误，最多尝试 `LLM_MAX_RETRIES + 1` 次，间隔为 `6 × 3^attempt` 秒；流开始迭代后的中途异常已离开该重试范围。
4. 主模型尝试耗尽且配置备用模型时，发布 `model.fallback` 后调用备用模型。
5. 从最终 response usage 读取 token，计入当前请求预算。

Orchestrator 外层还会对逃出模型层、工具或流消费阶段的瞬时错误最多重新进入 reply loop 两次，其中包括模型流中途失败。它复用同一个可变 AgentState，只把 `inputs` 改为 `[]` 以避免再次显式注入买家消息，并不会把上下文、已经执行的工具副作用或已经发布的事件回滚到本轮开始状态。因此这不是事务意义上的“整轮重试”；已发送到前端的 token 可能重复，写工具若已产生副作用也不能依赖该重试自动撤销，直到成功的 `final.result` 才会覆盖临时气泡，见 [orchestrator.py](../app/application/agents/orchestrator.py#L300)。

请求级 token 预算当前只会在非 `main` 档优先切备用模型，`minimal` 档再加入简洁提示。`budget.py` 虽定义“fallback 档不再调用 LLM”的常量和注释，但主链没有相应硬短路，不能把它写成已实现行为。

### Step 7：成功收尾

正常得到最终 `Msg` 后依次执行：

1. `_guard_final_text()` 按固定正则脱敏 `shopping_session_id` 键值形式、`sk-` API key 形态、枚举主机名的内部 URL 和已列出的内部工具名；它不是对所有内部标识或地址的通用识别。
2. 可选 drift check。
3. `AgentState.summary` 变化时发布 `context.compressed`。
4. 发布 `final.result`。
5. 若进入本轮前 `AgentState.context` 为空、query 未命中固定正则拒绝规则且回复不是错误，则写入语义缓存。

输出审核名单当前没有 `forget_preference_tool`，也没有四个 AgentScope Task 工具名 `TaskCreate`、`TaskUpdate`、`TaskList`、`TaskGet`，因此不能说它覆盖了所有内部工具名，见 [output_guard.py](../app/infrastructure/security/output_guard.py#L25) 和 [main_agent.py](../app/application/agents/main_agent.py#L113)。

漂移检测也只是部分接线：Composition Root 构造 `DriftDetector()` 时没有传可选 judge；Orchestrator 观测工具结果时只传动作摘要和“hits 是否为空”，没有传 token 消耗或偏好黑名单命中。检测发生在最终文本已经生成、审核之后，命中时只记录日志并发布 `error`，不会重写或阻止随后发布的 `final.result`，见 [composition.py](../app/composition.py#L202) 和 [orchestrator.py](../app/application/agents/orchestrator.py#L352)。

### Step 8：异常与 finally

`handle_intent()` 捕获普通 `Exception` 后发布 `error`，并返回 `[error] {err}`。这个异常分支不会发布 `final.result`；当前前端又不读取 HTTP body，所以 UI 不会把该错误文本加入聊天 turn，只会在事件时间线看到 `error`。

无论缓存命中、正常完成还是捕获异常，`finally` 都会尝试：

- `SessionRegistry.persist()` 保存 `agent.state.model_dump_json()`。
- 保存 buyer turn、agent turn、耗时和本轮除 `token.delta` 外的事件。
- 清理本轮 LoopDetector / DriftDetector 状态。
- reset `ShoppingContext`。

`AgentState` 的完整定义在 AgentScope 依赖中；本仓直接使用 `context`、`summary`、`tasks_context.tasks` 和 `permission_context.allow_rules`。

## 4. 运行时工具分支

MainAgent 的可选下一步包括直接回答、直接调用业务工具、调用 AgentScope Task 工具，或通过 `task_dispatch` 派发子 Agent。下面只描述工具一旦被选中后的确定性链路。

### 4.1 商品检索

```text
MainAgent 或 SearchAgent
→ FunctionTool(product_search_tool)
→ ToolResilienceMiddleware
→ ProductSearchSpec
→ CatalogSearchUseCase.execute()
   ├─ embed(normalized_query)；Redis 可用时先经过 CachedEmbeddingClient
   ├─ Qdrant search(top_n=8)
   ├─ ProductRepository.find_by_ids()
   ├─ 可选 HTTP rerank
   ├─ 向量异常或无候选时 keyword_2gram
   ├─ ship_to / price_max_major 硬过滤
   └─ 组装 ProductCard 与可选 landed_price
→ tool.result（含 hits）
→ ToolChunk(JSON) 返回 AgentScope
```

准确边界：

- 策略字段为 `embedding_rerank`、`embedding_only` 或 `keyword_2gram`。
- `build_container()` 在 RedisCache 可用时以 `CachedEmbeddingClient` 包裹原始 embedding 客户端，缓存键由 embedding 模型与文本生成，TTL 为 7 天；商品检索、偏好相关性和语义缓存等共享同一包装后的客户端，见 [composition.py](../app/composition.py#L139) 和 [cached_embedding_client.py](../app/infrastructure/cache/cached_embedding_client.py#L19)。
- “向量异常降级关键词”只覆盖 `CatalogSearchUseCase` 实际捕获到的 embedding/Qdrant 异常和空候选。embedding HTTP 超时与商品工具外层超时同为 15 秒，外层取消可能先发生并直接返回工具超时，不能保证所有向量故障都得到关键词结果，见 [catalog_search.py](../app/application/usecases/catalog_search.py#L104)、[openai_embedding_client.py](../app/infrastructure/embedding/openai_embedding_client.py#L26) 和 [resilience.py](../app/infrastructure/resilience.py#L30)。
- `category` 只在关键词降级时加权，不是向量路径的硬过滤条件。
- `price_max_major` 用目标币种换算后的主 SKU（Stock Keeping Unit，库存单位）价格判断；商品卡普通 `price_major/currency` 仍保留 SKU 原币种，到手价才按 `target_currency` 返回。
- `ship_to` 不在 `product.ships_to` 时，商品在组卡前已被过滤；`landed_price.unavailable_reason` 主要覆盖商品声明可送达、但静态规则表不支持该目的国的情况。
- `landed_price` 固定按 `primary_sku()`、数量 1 计算，只是搜索卡片估算；它不会写入订单行，也不参与 `Order.total_amount()`。`price_max_major` 同样只比较主 SKU 商品价，不含运费与关税，见 [catalog_search.py](../app/application/usecases/catalog_search.py#L234) 和 [order.py](../app/domain/order/order.py#L78)。
- 被硬条件挡掉的候选最多以 3 条摘要写入 `filtered_out`。

### 4.2 品类知识 RAG（Retrieval-Augmented Generation，检索增强生成）

```text
MainAgent 或 SearchAgent
→ category_insight_tool(question, top_k)
→ KnowledgeBase.search(queries=[question], top_k=top_k)
→ QdrantStore 检索 knowledge/*.md chunks
→ insights[{content, source, score}]
→ ToolChunk(JSON)
```

启动阶段 `bootstrap_category_knowledge()` 使用 `TextParser` 和 `ApproxTokenChunker(chunk_size=512, overlap=50)` 建库，以文件 stem 作为 `document_id` 跳过已有文档。它没有按内容哈希更新旧文档：文件内容改变而 stem 不变时，现有 collection 中的文档不会自动刷新。

### 4.3 子 Agent 派发

```text
MainAgent 调 task_dispatch(subagent_type, demands)
→ 发布 agent.dispatch
→ SearchAgentFactory.build() 或 TradeAgentFactory.build()
→ 新 AgentState，不恢复 MainAgent 历史
→ SearchAgent 可按当前 buyer 读取并注入相关偏好
→ worker.reply(inputs)
→ 子 Agent 调用自己的工具
→ 最终文本作为 task_dispatch ToolChunk 返回 MainAgent
→ 发布 task_dispatch tool.result（含耗时）
```

- `subagent_type` 只允许 `search_agent` / `trade_agent`。
- SearchAgent 有商品、品类知识和可选 Web 搜索工具；只有配置 `TAVILY_API_KEY` 时才注册 `web_search_tool`。调用后它向 Tavily HTTP API 请求结果，把每条 content 截断为 500 字符后放进 ToolChunk；工具事件只记录命中数，不带完整搜索内容，见 [web_search_tool.py](../app/application/tools/web_search_tool.py#L24)。TradeAgent 有三个订单工具。
- 两者 `ReActConfig.max_iters=6`；MainAgent 为 15。
- `task_dispatch` 标记 `is_concurrency_safe=True`，表示框架可以并发执行同轮的多个派发；是否真的产生多个并发调用仍由模型输出决定。
- SearchAgent 的偏好注入还受 `PREFERENCE_SUBAGENT_INJECT` 控制；关闭时子 Agent 不读取这份 hint，MainAgent 自身的偏好注入不受该开关控制，见 [main_agent.py](../app/application/agents/main_agent.py#L121) 和 [settings.py](../app/infrastructure/settings.py#L89)。
- 子 Agent 的业务工具事件直接发布到同一个 session；只有子 Agent 最终文本作为调度工具结果返回 MainAgent。

### 4.4 AgentScope Task 计划工具

MainAgent 还直接注册 `TaskCreate`、`TaskUpdate`、`TaskList`、`TaskGet`。这些工具操作 `AgentState.tasks_context.tasks`，用于模型自己的计划管理，不是 Redis 队列任务，也不等于后台 `IntentTask`。每个 Task 工具完成时，Orchestrator 从当前 AgentState 生成 `plan.update`；它们没有项目自己的 `ToolResilienceMiddleware` 或 Harness，最终随整个 AgentState 由 `SessionRegistry.persist()` 保存，见 [main_agent.py](../app/application/agents/main_agent.py#L113) 和 [orchestrator.py](../app/application/agents/orchestrator.py#L343)。

### 4.5 创建、查询与取消订单

创建链路：

```text
create_order_tool(items, shipping_address)
→ 从 ShoppingContext 读取 buyer_id
→ dict → OrderItemInput / Address
→ PlaceOrderUseCase.execute()
   ├─ 查 Product / SKU
   ├─ Sku.deduct_stock()
   ├─ 创建 OrderLine 价格快照
   ├─ OrderRepository.next_order_id()
   ├─ Order.place()：DRAFT 后立即 confirm 为 CONFIRMED
   └─ OrderRepository.save()
→ Order.snapshot()
```

关键数据边界：

- 正数量的正常路径中，查商品、查 SKU、构造订单行或 `Order.place()` 失败会尝试回补已记录的库存，但这不是无条件回滚保证。当前没有在变更库存前校验 `quantity > 0`：`Sku.deduct_stock(-1)` 会把库存增加 1，之后 `OrderLine` 才拒绝负数量，而 `restore_stock(-1)` 又会抛错，最终留下被增加的库存，见 [order_usecases.py](../app/application/usecases/order_usecases.py#L35)、[sku.py](../app/domain/catalog/sku.py#L27) 和 [order_line.py](../app/domain/order/order_line.py#L21)。
- `OrderRepository.save()` 位于回滚 `try/except` 之外；保存失败时，当前代码不会回补已扣库存。
- 取消只允许 `CONFIRMED`。代码先把订单对象改为 `CANCELLED`，再回补当前进程的商品库存，最后保存订单；保存失败也没有撤销库存回补。
- 商品和库存不落数据库，也不在 API / 多 worker 进程间共享。SQL 订单持久化不等于库存具有跨进程一致性。
- `DATABASE_URL=file` 时，Composition Root 使用进程内 `InMemoryOrderRepository`，而不是文件订单仓储；worker 创建的订单可能无法被 API 进程的 REST 查询/取消看到，多个 worker 也各持有自己的订单集合，见 [composition.py](../app/composition.py#L168)。
- 下单 UseCase 不校验 `shipping_address.country` 是否属于商品的 `ships_to`，也不把搜索卡片中的运费、关税或 landed price 写入订单。订单总额只汇总订单行的 SKU 单价乘数量；地址中的 country 在当前 MVP（Minimum Viable Product，最小可行产品）主要用于保存和展示，见 [order_usecases.py](../app/application/usecases/order_usecases.py#L25)、[order.py](../app/domain/order/order.py#L78) 和 [address.py](../app/domain/order/address.py#L2)。
- `Order` 要求所有订单行币种一致，没有汇率换算；一次提交混合币种 SKU 会在 `Order.place()` 构造聚合时失败并进入上述回补流程，见 [order.py](../app/domain/order/order.py#L45)。
- 查询与取消 UseCase 只按 `order_id` 操作，没有校验当前 buyer 是否属于该订单。

### 4.6 长期偏好

- 主 Agent 读：`Orchestrator._build_inputs()`。
- SearchAgent 子任务读：`task_dispatch._preference_hint()`；TradeAgent 不注入。
- 写：`remember_preference_tool()` → `PreferenceStore.append()`。
- 删：`forget_preference_tool()` → `PreferenceStore.delete(buyer_id, statement)`，按 statement 精确匹配；未命中时返回现有偏好供模型重试。
- 缓存隔离：`_preference_scope()` 使用全量偏好的渲染结果生成指纹，偏好改变后进入新缓存桶。

## 5. 事件与状态变化

### 5.1 主要状态载体

| 状态 | 作用域 | 主要变化 |
| --- | --- | --- |
| `SubmitIntentRequest/Input/Output` | 单次 HTTP 请求 | 接口对象到应用对象再到响应 |
| `ShoppingContextSnapshot` | 当前异步请求 | 携带 session、buyer、locale、currency；后两者尚未形成模型/工具硬约束 |
| `TokenBudget` | 当前请求及继承 ContextVar 的子任务 | 累计模型 usage |
| `AgentState` | MainAgent 会话；子 Agent 单次实例 | context、summary、tasks、permissions |
| `IntentTask/TaskStatus` | Redis 队列任务 | 正常预期为 queued → running → done/failed；竞态下 running/done 可能被 queued 覆盖 |
| `Product/Sku/Order` | 业务对象 | 下单扣当前进程库存；取消改状态并回补执行进程的库存副本 |
| `TradeEvent` | 过程事件 | EventBus → 可选 Redis 背板 → WebSocket/持久化 |

### 5.2 工具结果的两条去向

1. `ToolChunk` 返回 AgentScope，成为后续模型调用可见的 observation（观察结果）。
2. 工具调用 `TradeEventBus.publish()`，供 WebSocket UI 和轮末事件持久化。

商品搜索的 `hits` 同时出现在 ToolChunk JSON 与 `tool.result.payload.hits`；订单 snapshot 同时出现在 ToolChunk 和事件的 `order` 字段中。

### 5.3 事件可靠性

- `TradeEventBus` 给每个订阅者创建无界 `asyncio.Queue`，单个慢订阅者不会阻塞发布者，但队列可能持续增长。
- 跨进程事件通过 Redis Pub/Sub fire-and-forget 广播，不提供持久化或补发。
- API 的远端事件转发协程在背板监听异常时只记录 warning 随后结束，没有自动重连；此后 worker 仍可能完成任务并写 task status，但实时事件不会继续转发到该 API 进程，见 [server.py](../app/presentation/server.py#L57)。
- 对话存储在轮末保存“Orchestrator 建立 trace 订阅后、当前进程 EventBus 捕获到的”非 `token.delta` 事件；API 入队时的 `task.queued` 和 worker 进入 Orchestrator 前发布的 `task.started` 不在该订阅窗口内。WebSocket 重连也不会读取这些历史记录。
- `conversation_events` 保存当前 trace 捕获到的部分非 token 事件轨迹，不是完整审计，也不是实时消息队列。
- 输出审核只处理最终文本，不处理 WebSocket 工具事件。订单 `tool.result` 会携带包含收货人、地址和电话的 order snapshot；结合 WebSocket 只凭 session ID 订阅，这不仅是事件完整性问题，也是个人信息暴露边界，见 [order_tools.py](../app/application/tools/order_tools.py#L75)、[order.py](../app/domain/order/order.py#L84) 和 [connection.py](../app/presentation/connection.py#L25)。

## 6. 中间件、结束与失败路径

### 6.1 实际中间件覆盖

| 对象 | 当前中间件 |
| --- | --- |
| 三个 Agent | `TracingMiddleware`；`REPLY_TOKEN_BUDGET > 0` 时增加 `ReplyBudgetControlMiddleware` |
| 搜索、RAG、Web、订单工具 | `ToolResilienceMiddleware` |
| `task_dispatch`、两个偏好工具 | 可选 `HarnessToolMiddleware` 在外，`ToolResilienceMiddleware` 在内 |
| 四个 AgentScope Task 工具 | 没有项目 Tool middleware |

Harness 的前置顺序、循环检测、返回 Schema 检查和 L3 内容过滤只对它实际包裹的三个 MainAgent 自有工具生效。`assertions.py` 虽为商品和订单工具定义了规则，但这些工具当前没有挂 Harness，因此“先检索再下单”等规则不会在真实订单调用链中硬拒。

`ToolResilienceMiddleware` 会把最后一个 `ToolChunk` 的 `ERROR` 统一计作熔断失败，不区分下游基础设施故障与“订单不存在”“参数非法”等业务错误。熔断键按工具名而不是 buyer/session 隔离；连续的错误输入可让同进程内、或开启共享熔断时所有进程中的合法调用一起被拒绝，见 [resilience.py](../app/infrastructure/resilience.py#L179) 和 [shared_breaker.py](../app/infrastructure/shared_breaker.py#L46)。

### 6.2 正常结束与短路

- MainAgent 的每次 reply 尝试最多 15 次 ReAct iteration；每个新建的 SearchAgent / TradeAgent 实例最多 6 次。这不是一次 HTTP 请求的累计绝对上限：Orchestrator 可重新进入 MainAgent reply loop，一次请求也可能派发多个子 Agent，见 [main_agent.py](../app/application/agents/main_agent.py#L106)、[search_agent.py](../app/application/agents/search_agent.py#L84) 和 [trade_agent.py](../app/application/agents/trade_agent.py#L79)。
- 正常结束以 `reply_stream(..., yield_final_msg=True)` 产出最终 `Msg` 为项目可见标志。
- 语义缓存命中会跳过整个 Agent loop。
- 工具超时、熔断或工具自身 ERROR 只终止当前工具调用，Agent 仍可换工具或回答。
- Harness 硬拒也只返回当前工具的 ERROR ToolChunk，不结束整轮；当前真实订单工具不受该 Harness 规则保护。
- LoopDetector 只追加收敛提示，不强制停止 Agent。

### 6.3 模型持续失败

```text
主模型调用
→ transient error：模型层指数退避重试
→ 尝试耗尽且有备用模型：发布 model.fallback 并调用备用模型
→ 异常仍逃出
→ Orchestrator 对 transient error 最多重试整轮 2 次
→ 仍失败：发布 error，返回 [error]，不发布 final.result
```

非 transient error 不会在 `_call_with_fallback()` 中重试。

### 6.4 队列任务结束

- `handle_intent()` 正常返回且 `TaskStatus=done` 写入成功后，handler 正常结束，队列层随后执行 `XACK`；即使返回文本以 `[error]` 开头，也仍会尝试写 `done`。
- worker 的 `try` 同时包住 `handle_intent()` 和 `TaskStatus=done` 写入，因此两者任一抛错都会进入 `failed` 写入并重新抛出；写 `running` 位于该 `try` 之前，若它失败则不会写 `failed`。
- `_handle_one()` 在异常时不 ack；达到投递次数上限后写 dead stream 并 ack。
- 但当前没有 pending reclaim 调用，因此“失败后自动再次投递并最终进入死信”并非完整闭环。投递次数逻辑只有消息被重新领取后才有机会继续执行。
- 同步 HTTP 等待超时只结束等待，不会取消 worker 中的任务。

### 6.5 worker 与部署配置

- worker 在启动早期无条件为 `SIGTERM`、`SIGINT` 调用 `loop.add_signal_handler()`。原生 Windows 默认事件循环不实现该接口，会在 `container.startup()` 前抛 `NotImplementedError`；当前 worker 主链应按 Linux/Docker 运行理解，见 [worker.py](../app/worker.py#L47)。
- Compose 中 app 与 worker 的环境变量集合并不相同。app 透传 `LLM_MAX_RETRIES`、`SEMANTIC_CACHE_THRESHOLD`、`QUEUE_WAIT_SECONDS` 等，worker 没有透传前两项；队列模式下真正执行 Agent 的是 worker，因此宿主机对这些变量的自定义值可能只影响 API 进程或被 worker 的默认值替代，见 [docker-compose.yaml](../docker/docker-compose.yaml#L18) 和 [docker-compose.yaml](../docker/docker-compose.yaml#L58)。
- 当前 Compose 对 app 和 worker 都没有显式透传 `TAVILY_API_KEY`、reranker、OTLP（OpenTelemetry Protocol，遥测协议）、输出审核、漂移检测、token 预算和偏好注入等可选配置。若只给 app 补这些变量，队列模式的实际 Agent 行为仍不会改变；需要把 Agent 行为相关配置同步到 worker，并把两边的有效配置纳入启动检查。

## 7. 当前实现中最值得警惕的边界

| 边界 | 代码事实 | 影响 |
| --- | --- | --- |
| 身份与租户隔离 | buyer/session/task/order ID 都没有认证和 ownership 校验 | 知道或复用标识即可访问其他会话事件、AgentState、任务或订单 |
| 同 session 并发 | `SessionRegistry` 无 session 级锁 | 首次访问可能创建两个 Agent 并互相覆盖；已有实例可能被并发操作 |
| 跨 worker 会话状态 | 队列无 session affinity，SessionStore 覆盖写无版本检查 | 不同 worker 可从同一旧快照分叉执行，最后保存者覆盖另一分支的上下文 |
| 写操作确认 | Prompt 要求确认，但工具权限被项目规则直接放行 | 模型违反 Prompt 时，后端没有确认状态阻止下单或取消 |
| 同 session 队列结果关联 | `_await_result()` 按 session 接收不带 task ID 的 `final.result` | 同一 session 并发同步请求时，等待者可能拿到另一任务的最终文本 |
| 队列状态写入 | API 在 `XADD` 后才无条件写 `queued` | 可覆盖 worker 已写入的 `running/done`，使状态倒退并导致同步等待超时 |
| 队列并发上限 | 两条 Stream 分别应用同一个 `XREADGROUP COUNT` | 两边同时有消息时在途任务可超过 `WORKER_CONCURRENCY` |
| Stream 保留 | 处理后只 `XACK`，无 `XDEL/XTRIM` | 普通、大请求和死信 Stream 历史持续增长 |
| 缓存对话连续性 | 缓存命中不更新 AgentState | 下一轮上下文问题可能无法引用缓存轮次 |
| 缓存安全与新鲜度 | 正则拒绝名单并非语义判定，桶不含 locale/currency 与业务数据版本 | 写意图可能误缓存，也可能复用旧币种、旧库存或旧规则回复 |
| 偏好撤回连续性 | 删除 Store 记录不会删除 AgentState 中的旧偏好 hint | 已撤回偏好在旧上下文中仍可能继续影响模型 |
| 偏好执行 | dislike 只通过 Prompt/hint 影响模型，不是检索硬过滤 | 原始工具 hits 和前端商品卡仍可能含买家排斥项 |
| 队列业务幂等 | `SET NX` 只防重复入队，worker/订单层没有 task 幂等记录 | 重复消费可能重复执行写操作 |
| 多进程库存 | 商品仓储和 SKU 库存按进程内存隔离 | API、多个 worker 之间库存不一致，SQL 订单也无法解决 |
| 订单原子性 | 库存变化与订单保存不在同一事务 | 保存失败可能留下错误库存 |
| 数量校验顺序 | 先调用 `deduct_stock()`，后由 `OrderLine` 校验正数 | 负数量可增加库存，回补又失败 |
| 跨境计价闭环 | 搜索估算 landed price，下单不校验 ships_to 且只累计 SKU 货价 | 展示到手价不等于订单总价或可配送承诺；混币订单直接失败 |
| 订单号生成 | SQL 仓储用订单总数加一 | 并发下单可能生成相同编号，并进一步触发保存失败与库存偏差 |
| 订单授权 | 查询/取消只按 `order_id` | 知道订单号即可操作，缺少 buyer ownership 校验 |
| Harness 接线 | 商品/订单工具未挂 Harness | 已定义的顺序、Schema、L3 过滤规则不生效 |
| pending 恢复 | `claim_stale()` 未被调用 | worker 崩溃后的任务可能长期滞留 |
| WebSocket 恢复 | 无事件序号、补拉或重放 | 断线期间过程/最终事件可能丢失 |
| 前端结果通道 | 前端忽略 HTTP final_text，提交不要求 WS 已连接 | HTTP 成功但 final.result 丢失时，聊天区仍没有最终回复 |
| 异常展示 | Orchestrator 异常不发 `final.result`，前端忽略 HTTP body | 错误文本不会进入聊天气泡 |
| 流式输出审核 | 原始 `token.delta` 先发送，完成后才审核最终文本 | 最终脱敏无法撤回已显示的敏感 token，且流式 token 不入审计 |
| 前端派生卡片 | 只查找最近一条非空 hits，卡片来自原始工具事件 | 零命中、缓存命中或报错后仍可能展示旧卡，且不一定对应最终推荐 |
| 前后端事件契约 | 前端类型与标签缺少 `cache.hit`、`task.queued`、`task.started` | 运行时退回通用展示，类型、样式和专用摘要与后端漂移 |
| RAG 更新 | document stem 已存在即跳过 | 同名知识文件更新不会自动重建索引 |
| Agent 缓存 | `_agents` 无淘汰 | 长期运行时会话实例数量只增不减 |
| 模型限流作用域 | `GatewayThrottle` 按进程构造 | 多 worker 总并发不是单个配置值，无法形成集群级配额 |
| worker 可移植性 | 依赖 `loop.add_signal_handler()` | 原生 Windows 默认事件循环下启动失败 |
| Compose 配置 | app/worker 透传变量集合不同 | 队列开启后 API 配置值不一定作用于实际执行 Agent 的 worker |
| 健康与运行时降级 | `/health` 始终返回 `status=ok`；已配置 Redis 失联不切回直跑 | 探针可能继续判定健康，请求却因数据库或队列不可用而失败 |

补充两个容易被接口命名掩盖的事实：`queue_position` 当前返回的是两条 Stream 的总 lag，不是该 task 的真实排队位置；SQL 对话存储则分别提交 buyer turn、agent turn 和事件批次，中途失败时可能只保存本轮的一部分。两者都不应被理解为精确队列位置或整轮原子审计记录，见 [redis_stream_queue.py](../app/infrastructure/queue/redis_stream_queue.py#L67) 和 [orchestrator.py](../app/application/agents/orchestrator.py#L275)。

这些是当前代码边界，不应在文档中包装成已经完成的可靠性或安全能力。
