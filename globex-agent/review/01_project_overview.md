# 01 项目总览与核心文件定位

> 阅读目标：先建立 Globex 的源码地图，再进入一次请求的调用链。本文只陈述当前仓库可直接确认的实现；AgentScope 的内部调度行为只描述到本项目调用边界。
>
> 一次请求的详细过程见 [02 一次用户请求的完整调用链追踪](02_core_call_chain.md)。

## 1. 项目是什么

Globex 是一个面向跨境购物场景的自然语言 Agent 服务。前端提交购物诉求后，MainAgent 可以直接调用业务工具，也可以通过 `task_dispatch` 临时创建 SearchAgent 或 TradeAgent 完成子任务。HTTP（Hypertext Transfer Protocol，超文本传输协议）端点会返回文本结果：直跑模式取自 Orchestrator，队列模式则等待 worker 结果或返回固定超时文本；正常完成或语义缓存命中时，过程事件与 `final.result` 还会通过 WebSocket 推送给前端。异常被 Orchestrator 捕获后则只发布 `error` 并在 HTTP 正文中返回 `[error]`，不会发布 `final.result`。

当前代码已接入的主要能力：

- 商品检索：query embedding（向量化）→ Qdrant 向量召回 → 可选 rerank（精排）；被 `CatalogSearchUseCase` 捕获的向量异常或空候选会降级为关键词 2-gram 召回，但外层工具超时或协程取消不保证进入这条降级链。
- 品类知识 RAG（Retrieval-Augmented Generation，检索增强生成）：检索 `knowledge/*.md` 的知识片段。
- 跨境到手价：传入 `ship_to` 时，按静态汇率、运费、免税额和关税规则，为商品主 SKU（Stock Keeping Unit，库存单位）、数量 1 计算展示估价；它不是订单最终结算金额。
- 订单：创建、查询、取消；创建时扣减执行进程的商品内存库存，取消时回补执行取消用例的进程内库存副本。
- 多轮会话：按 `shopping_session_id` 缓存 MainAgent，并持久化 AgentScope `AgentState`；但语义缓存命中会绕过 Agent loop，不会把该轮问答写入 `AgentState`，见 5.1 节。
- 长期偏好：按 buyer 保存、筛选、注入和精确删除偏好。
- 实时事件：发布 token、工具、子 Agent、计划、缓存、模型回退等事件；正常完成或缓存命中时再发布最终结果。
- 可选基础设施：Redis 语义缓存、embedding 缓存、Stream 队列、跨进程事件背板、共享熔断，以及 OTLP（OpenTelemetry Protocol，遥测协议）链路导出。

### 1.1 代码明确限定的边界

- `Order` 只有 `DRAFT → CONFIRMED → CANCELLED`，没有支付、发货、物流或退款流程，见 [order.py](../app/domain/order/order.py#L23)。
- 商品目录始终来自 `build_seed_products()`，保存在每个进程自己的 `InMemoryProductRepository` 中；没有商品数据库表。worker 下单扣减的是该 worker 的副本，API（Application Programming Interface，应用程序编程接口）直连取消可能给另一份从未扣减过的副本加库存，进程重启又会恢复 seed 库存，因此库存不具备跨进程一致性和重启持久性，见 [in_memory_repositories.py](../app/infrastructure/persistence/in_memory_repositories.py#L19) 和 [order_usecases.py](../app/application/usecases/order_usecases.py#L79)。
- 汇率、关税、免税额和运费是源码内的静态 MVP（Minimum Viable Product，最小可行产品）规则，不是实时外部报价，见 [exchange_rate.py](../app/domain/catalog/exchange_rate.py#L13) 和 [tariff_schedule.py](../app/domain/shipping/tariff_schedule.py#L18)。
- Web 搜索只有配置 `TAVILY_API_KEY` 后才注册，见 [search_agent.py](../app/application/agents/search_agent.py#L57)。
- 当前没有终端用户认证或租户授权：`buyer_id`、`shopping_session_id`、`task_id` 和 `order_id` 都由客户端提供或持有。订单查询/取消只接收 `order_id`，WebSocket 只凭 `shopping_session_id` 订阅，任务查询只凭 `task_id`，见 [server.py](../app/presentation/server.py#L130) 和 [connection.py](../app/presentation/connection.py#L25)。
- 当前队列消费循环只读取新消息；已有 `claim_stale()`，但没有调用者，因此 worker 崩溃后的 pending 消息不会由现有主链自动领取，见 [redis_stream_queue.py](../app/infrastructure/queue/redis_stream_queue.py#L101)。
- `claim_stale()` 本身也还不是可直接接入的完整恢复接口：它只对普通 `_STREAM` 执行 `XAUTOCLAIM`，没有处理大请求 `_LARGE_STREAM`，且返回值丢失原始 stream 与 message ID，调用方无法据此准确 `XACK`，见 [redis_stream_queue.py](../app/infrastructure/queue/redis_stream_queue.py#L198)。
- 队列入口的 Redis `SET NX` 只是“重复提交去重”，不是端到端业务幂等：指纹只有 session 与 query，不含 buyer；worker 执行前也不按 task 状态去重，见 [server.py](../app/presentation/server.py#L222) 和 [worker.py](../app/worker.py#L51)。
- Agent 工具路径中的下单/取消确认目前仅由 Prompt 约束；项目权限规则会直接放行业务写工具，没有后端确认令牌或确认状态机。直连的 `POST /commerce/orders/{order_id}/cancel` 甚至不经过 Prompt，而是直接调用取消 UseCase，见 [permissions.py](../app/application/agents/permissions.py#L16)、[globex.yml](../app/application/prompts/globex.yml#L59) 和 [server.py](../app/presentation/server.py#L194)。
- SQL（Structured Query Language，结构化查询语言）订单号通过“当前订单总数 + 1”生成，并发创建时可能碰撞；保存失败又处于库存回滚范围之外，见 [repositories.py](../app/infrastructure/persistence/sql/repositories.py#L247)。
- 商品卡的到手价只针对主 SKU、数量 1；价格上限只比较换算后的主 SKU 商品价，而订单总额仅汇总订单行货价。下单用例不会依据收货地址校验 `ships_to`，也不会把运费和关税写入订单；混合币种订单行则会被领域对象拒绝。因此搜索展示的“可送达”和“到手价”不能视为订单结算或履约承诺，见 [catalog_search.py](../app/application/usecases/catalog_search.py#L129)、[catalog_search.py](../app/application/usecases/catalog_search.py#L234) 和 [order.py](../app/domain/order/order.py#L45)。
- `/health` 即使探测到数据库或 Redis 错误，仍返回 `status="ok"`；配置了 Redis URL 也只代表创建了客户端，不代表连接可用，运行时失败不会自动切回 API 进程直跑，见 [server.py](../app/presentation/server.py#L105)。
- 入队顺序是先 `XADD`、后写 `TaskStatus(state="queued")`；worker 若在两步之间完成状态更新，API 随后的写入可能把 `running` 或 `done` 倒退覆盖成 `queued`。消费端又以同一个 `count=free_slots` 同时读取 normal、large 两条 Stream；Redis 的 `COUNT` 是每条 Stream 的上限，一次读取最多可能取得 `2 × free_slots` 条消息，因此实际在途任务数不一定受 `WORKER_CONCURRENCY` 严格约束。成功和死信路径只 `XACK`、未执行 `XDEL` 或 `XTRIM`，三条 Stream 都会持续增长，见 [server.py](../app/presentation/server.py#L242)、[redis_stream_queue.py](../app/infrastructure/queue/redis_stream_queue.py#L119) 和 [Redis XREADGROUP 文档](https://redis.io/docs/latest/commands/xreadgroup/)。
- 队列同步等待只按 `shopping_session_id` 订阅 `final.result`，事件中没有 `task_id`；同一 session 并发提交多个同步请求时，多个等待者可能都返回最先完成的那一条结果，见 [server.py](../app/presentation/server.py#L258) 和 [orchestrator.py](../app/application/agents/orchestrator.py#L175)。
- 当前前端不读取 HTTP 返回正文，聊天回复完全依赖 WebSocket `final.result`；提交按钮又不以 WebSocket 已连接为前提。因此首次连接尚未建立、断线重连、事件转发中断，或 Orchestrator 捕获异常只发 `error` 时，即使 HTTP 返回了正常的 200 响应，最终文本也可能不出现在聊天区；worker 还会把 Orchestrator 返回的 `[error]` 记录成 `done`，见 [App.tsx](../frontend/src/App.tsx#L79)、[orchestrator.py](../app/application/agents/orchestrator.py#L178) 和 [worker.py](../app/worker.py#L51)。
- `token.delta` 在 `reply_stream()` 消费期间立即推送，`_guard_final_text()` 则要等整段回复完成后才审核最终文本。已经通过 WebSocket 发出的内部工具名、密钥形态或内部 URL 无法由最终脱敏撤回，而且 token 事件不写入对话事件审计，见 [orchestrator.py](../app/application/agents/orchestrator.py#L126)、[orchestrator.py](../app/application/agents/orchestrator.py#L264) 和 [orchestrator.py](../app/application/agents/orchestrator.py#L329)。
- `locale`、`currency` 会进入请求快照和持久化元数据，但 `_build_inputs()` 只把原始问句和偏好提示交给模型，商品工具也不会自动读取请求快照中的币种，而是使用参数默认值 `CNY`。因此这两个字段目前不能保证回复语言或商品换算币种，见 [orchestrator.py](../app/application/agents/orchestrator.py#L140)、[orchestrator.py](../app/application/agents/orchestrator.py#L411) 和 [product_search_tool.py](../app/application/tools/product_search_tool.py#L24)。
- 前端商品卡向后寻找最近一个“含非空 `hits` 的 `tool.result`”，不会在零结果、缓存命中、直接回答或错误时清除旧卡；它显示的还是模型最终筛选前的工具原始候选。同理，已经收到部分 token 后若只收到 `error`，`streaming` 也不会清空，见 [ProductCards.tsx](../frontend/src/components/ProductCards.tsx#L3) 和 [App.tsx](../frontend/src/App.tsx#L57)。
- 同 session 并发不只影响单进程内的 `SessionRegistry`：队列没有 session affinity（会话亲和）或串行化，不同 worker 可各自恢复同一份旧 `AgentState`，最终由 `SqlSessionStore.save()` 覆盖写，存在上下文分叉和最后写入覆盖窗口，见 [worker.py](../app/worker.py#L82)、[main_agent.py](../app/application/agents/main_agent.py#L171) 和 [repositories.py](../app/infrastructure/persistence/sql/repositories.py#L96)。
- `forget_preference_tool` 只从 `PreferenceStore` 删除记录，不会移除已写入 `AgentState.context` 的旧 `<buyer-preferences>` 消息；撤回的偏好在旧上下文被压缩或淘汰前仍可能影响模型，见 [forget_preference_tool.py](../app/application/tools/forget_preference_tool.py#L43) 和 [orchestrator.py](../app/application/agents/orchestrator.py#L411)。

## 2. 一张图看懂运行结构

```text
React 前端
  ├─ POST /commerce/intents ───────────────┐
  └─ WS /commerce/events ← 过程/最终事件    │
                                            ▼
FastAPI server ── 无队列 ──────────→ MainAgentOrchestrator
      │                                     │
      └─ 有队列 → Redis Stream → worker ────┘
                                            │
                       ┌────────────────────┼────────────────────┐
                       ▼                    ▼                    ▼
                  MainAgent           Session/Memory       TradeEventBus
                       │                                     │
              模型运行时选择分支                             └→ WebSocket
            ┌──────────┼───────────┐
            ▼          ▼           ▼
        直接业务工具  Task 工具  task_dispatch
                                   ├→ SearchAgent
                                   └→ TradeAgent
```

必须区分两部分：

- 固定入口：路由或 worker → `MainAgentOrchestrator.handle_intent()`；语义缓存命中时直接执行输出审核、事件和持久化，缓存未命中时才进入 `agent.reply_stream()`。
- 动态分支：是否调用工具、调用哪个工具、是否建 Task、是否派发子 Agent，由 Prompt、Tool schema、上下文和模型输出共同决定；项目中没有按意图写死的 `if/else` 路由。

## 3. 分层与模块职责

### 3.1 Presentation / 接口层

| 文件 | 职责 |
| --- | --- |
| [server.py](../app/presentation/server.py) | FastAPI 生命周期、REST / WebSocket 路由、直跑与队列分支 |
| [dto.py](../app/presentation/dto.py) | Pydantic DTO（Data Transfer Object，数据传输对象） |
| [connection.py](../app/presentation/connection.py) | 按 session 订阅事件并发送 WebSocket JSON |
| [App.tsx](../frontend/src/App.tsx) | 保存 buyer/session、提交意图、消费事件、渲染文本和商品卡 |

当前路由：

| 接口 | 入口 | 是否进入 Agent |
| --- | --- | --- |
| `GET /health` | `health()` | 否 |
| `POST /commerce/intents` | `submit_intent()` | 是；队列开启时先入队并同步等待 |
| `POST /commerce/intents/async` | `submit_intent_async()` | 是；仅队列开启时可用 |
| `GET /commerce/tasks/{task_id}` | `get_task()` | 否，只读任务状态 |
| `WS /commerce/events` | `commerce_events()` | 否，订阅 Agent 事件 |
| `GET /commerce/orders/{order_id}` | `get_order()` | 否，直连查询用例 |
| `POST /commerce/orders/{order_id}/cancel` | `cancel_order_endpoint()` | 否，直连取消用例 |

### 3.2 Composition Root / 组装根

[composition.py](../app/composition.py#L129) 是 API 与 worker 共用的依赖装配中心。`build_container()` 依次完成：

1. 加载配置并按需初始化 tracing（链路追踪）。
2. 创建商品仓储、EventBus、Qdrant 索引、embedding、可选 reranker 与知识库。
3. 根据 Redis 与队列开关创建缓存、Stream 队列和事件背板。
4. 根据 `DATABASE_URL` 选择 SQL 仓储，或 `file` 模式下的 JSON / 内存实现。
5. 创建熔断、LLM（Large Language Model，大语言模型）限流器和可选运行护栏。
6. 创建 UseCase、Agent factory、`SessionRegistry` 和 Orchestrator。

`Container.startup()` 尝试建 SQL 表、创建 Redis consumer group、建立商品向量索引和品类知识库。各步骤失败时记录告警；被商品检索用例捕获的向量调用异常或空候选有关键词召回兜底，但工具级超时和协程取消不保证完成该降级。品类知识建库失败不会注销 `category_insight_tool`，后续调用仍会尝试检索，可能因已有 collection 或依赖恢复而成功，也可能返回空结果或错误；它没有替代 RAG 降级链。数据库或队列初始化失败不会自动换成文件存储或直跑模式，因此“进程完成启动”不代表相关功能可用。

上述容错只覆盖对应 bootstrap（启动初始化）代码实际捕获的异常，不覆盖更早的构造阶段。`load_settings()`、tracing、Qdrant/KnowledgeBase 和数据库 engine 的构造没有统一兜底；其中 `build_app()` 还会在 lifespan 之前为 CORS（Cross-Origin Resource Sharing，跨源资源共享）再读取一次配置，所以配置校验或依赖构造失败仍可直接阻止应用启动，见 [server.py](../app/presentation/server.py#L89) 和 [composition.py](../app/composition.py#L129)。

### 3.3 Application / 应用层

| 目录 | 职责 | 核心对象 |
| --- | --- | --- |
| `application/agents/` | Agent 装配、会话实例管理、请求编排 | `MainAgentOrchestrator`、三个 Agent factory、`SessionRegistry` |
| `application/tools/` | 模型可见参数到 UseCase / Store 的适配，发布工具事件 | 商品、RAG、订单、偏好、子 Agent 工具 |
| `application/usecases/` | 确定性的业务流程 | `CatalogSearchUseCase`、三个订单 UseCase |
| `application/memory/` | 长期偏好筛选和提示消息渲染 | `PreferenceSelector` |
| `application/harness/` | 顺序、Schema、循环和漂移判定 | `SequencingTracker`、`LoopDetector`、`DriftDetector` |
| `application/prompts/` | 主/子 Agent 系统提示词 | `globex.yml`、`loader.py` |

MainAgent 注册搜索和订单业务工具、四个 AgentScope Task 工具、`task_dispatch` 及两个偏好工具，单轮 ReAct（Reason + Act，推理与行动）上限为 15。SearchAgent 和 TradeAgent 每次派发时新建，各自上限为 6，不继承 MainAgent 的历史状态。

### 3.4 Domain / 领域层

领域层保存不依赖 FastAPI、AgentScope 或数据库实现的业务模型与端口：

- `catalog/`：`Product`、`Sku`、`Money`、`ProductSearchSpec`、汇率和检索端口。
- `order/`：`Order`、`OrderLine`、`Address`、订单仓储端口。
- `shipping/`：到手价规则。
- `buyer/`：买家偏好及存储端口。
- `session/`：会话状态与对话流水端口。
- `queue/`：`IntentTask`、`TaskStatus` 和队列端口。

### 3.5 Infrastructure / 基础设施层

这一层实现外部系统和横切能力：

- `llm.py`：统一创建 Agent Chat Model，并包装并发限制、起跑间隔、重试、备用模型和 token 记账。
- `embedding/`、`vector/`、`rerank/`、`rag/`：两条检索链的基础设施。
- `persistence/`：SQL、JSON 文件和内存仓储实现。
- `cache/`、`queue/`：Redis 缓存、语义缓存、Stream 队列和 Pub/Sub 背板。
- `eventbus.py`：进程内按 session 发布/订阅事件。
- `resilience.py`、`harness_middleware.py`、`security/`：工具超时/熔断、工具护栏和最终完整文本脱敏；流式 token 不在最终输出审核的保护范围内。
- `context.py`、`budget.py`、`throttle.py`、`tracing.py`：请求上下文、预算、模型限流和可观测性。

## 4. Agent、工具与检索边界

### 4.1 MainAgent 的工具集合

| 来源 | 工具 |
| --- | --- |
| `SearchAgentFactory.build_tools()` | `product_search_tool`、`category_insight_tool`、可选 `web_search_tool` |
| `TradeAgentFactory.build_tools()` | `create_order_tool`、`query_order_tool`、`cancel_order_tool` |
| AgentScope | `TaskCreate`、`TaskUpdate`、`TaskList`、`TaskGet` |
| MainAgent 自有 | `task_dispatch`、`remember_preference_tool`、`forget_preference_tool` |

业务工具由 `FunctionTool` 包装，schema 来自函数签名；仓库中没有单独维护一份 OpenAI function schema 文件。

### 4.2 两条检索链

不要把商品召回和品类知识 RAG 混为一条链：

```text
商品检索：normalized_query
  → OpenAIEmbeddingClient（启用 Redis 时由 CachedEmbeddingClient 包装）
  → QdrantProductIndex
  → ProductRepository
  → 可选 HttpReranker
  → ship_to / price_max_major 硬过滤
  → ProductCard

品类知识：question
  → AgentScope KnowledgeBase.search
  → QdrantStore
  → knowledge/*.md chunks
  → insights
```

`category` 在向量路径中不是硬过滤条件，只在关键词降级评分时加权；真正的硬过滤条件是 `ship_to` 和 `price_max_major`，见 [catalog_search.py](../app/application/usecases/catalog_search.py#L129)。

### 4.3 中间件的实际覆盖范围

- 搜索、RAG、Web、订单、偏好和 `task_dispatch` 等项目业务工具都经过 `ToolResilienceMiddleware`，获得超时与熔断保护。
- `HarnessToolMiddleware` 只装配到 MainAgent 自有的 `task_dispatch`、`remember_preference_tool`、`forget_preference_tool`。
- 搜索与订单工具由子 Agent factory 预先创建，只挂 Resilience；四个 AgentScope Task 工具也没有项目 Harness。

因此，代码中虽然定义了商品/订单返回 Schema 检查和“先检索再下单”等顺序规则，但它们当前没有进入真实商品/订单调用链；L3 工具输出过滤也没有覆盖这些工具。

## 5. 状态与存储

### 5.1 四类容易混淆的“记忆”

| 状态 | 作用域 | 读写位置 |
| --- | --- | --- |
| `AgentState` | 一个 MainAgent 会话 | `SessionRegistry` 载入/保存 |
| 对话流水与事件 | 部分对话及非 token 事件轨迹 | `ConversationStore` |
| `BuyerPreference` | buyer 跨会话偏好 | 偏好工具、Orchestrator、SearchAgent 派发 |
| 语义缓存 | `AgentState.context` 为空且未命中固定拒绝正则的问句复用最终回复 | Redis `SemanticCache` |

偏好不是每轮全量注入：所有 `dislike` 按存储顺序保留；`like` 最多选择 top-k。相关性开关关闭时先按 `created_at` 倒序选出最新项，开启时按 embedding 相似度选出相关项，最终都恢复入选项在原列表中的相对顺序，避免注入块顺序抖动，见 [preference_selector.py](../app/application/memory/preference_selector.py#L70)。

这里的“`AgentState.context` 为空”不等于业务意义上的第一轮。缓存命中在 [orchestrator.py](../app/application/agents/orchestrator.py#L161) 中直接返回，不调用 `_build_inputs()` 或 `agent.reply_stream()`，因此该轮只写入对话审计存储，不会进入 AgentState，也不会产生新的商品工具结果。若下一轮问“刚才那个”，固定正则通常会因“刚才”而绕过缓存，但 Agent 仍看不到上一轮缓存回复；前端也可能继续显示更早的商品卡，这是当前多轮连续性和界面状态的明确缺口。

语义缓存的“安全”判断是固定正则启发式，不是意图分类或副作用证明；例如未出现在模式表中的英文写操作或同义表达仍可能通过。桶 key 只包含模型与 Prompt 指纹、buyer 和偏好 scope，不包含 `locale`、`currency`、商品/库存、汇率/关税、知识库版本或实际工具配置。因此它不能保证写操作全部排除，也不能保证命中回复仍符合当前语言、币种和业务数据，见 [semantic_cache.py](../app/infrastructure/cache/semantic_cache.py#L41) 和 [semantic_cache.py](../app/infrastructure/cache/semantic_cache.py#L101)。

偏好 Store 与 AgentState 也不是同一份状态。新增偏好会影响后续选择与缓存分桶，但撤回偏好只删除 Store 记录，已经作为 `UserMsg("memory_hint", ...)` 写入 AgentState 的旧提示不会被主动清除；因此“Store 中已删除”不能等同于“本会话上下文已忘记”。此外，偏好清空时 `_injected_preferences` 快照不会清除，之后重新创建完全相同的偏好时，当前进程内还可能被误判为已经注入。

### 5.2 存储实现

| 数据 | 默认实现 | `DATABASE_URL=file` 或可选实现 |
| --- | --- | --- |
| 商品目录与库存 | 每进程 `InMemoryProductRepository` + seed | 无数据库实现 |
| 商品向量 | Qdrant 本地嵌入模式 | 配 `QDRANT_URL` 后连接服务端 |
| 品类知识向量 | 本地 `QdrantStore` | 配 `QDRANT_URL` 后连接服务端 |
| 会话状态 | SQLite `agent_session_states` | JSON 文件 |
| 对话与事件 | SQLite 3 张表 | 单 session JSONL |
| 订单 | SQLite `orders`、`order_items` | 仅进程内订单仓储 |
| 买家偏好 | SQLite `buyer_preferences` | JSON 文件 |
| Redis 能力 | embedding 缓存随 `REDIS_URL` 启用；语义缓存还受独立开关控制；队列与背板还要求 `QUEUE_ENABLED` | 未配置 Redis 时全部关闭；关闭队列时仍可保留 Redis 缓存 |

SQLAlchemy 当前定义 7 张表：`conversation_sessions`、`conversation_messages`、`conversation_events`、`agent_session_states`、`orders`、`order_items`、`buyer_preferences`，见 [tables.py](../app/infrastructure/persistence/sql/tables.py#L42)。

## 6. 配置、运行模式与验证入口

### 6.1 关键配置的真实语义

| 配置 | 默认 / 条件 | 失败或关闭后的行为 |
| --- | --- | --- |
| `LLM_API_KEY` | 必填 | `load_settings()` 直接抛错，容器无法构建；项目不能在完全离线且无模型凭据时启动 API |
| `DATABASE_URL` | 默认 `DATA_DIR/globex.db` 的 SQLite | 特殊值 `file` 才使用 JSON 会话/偏好/对话和内存订单；SQL 初始化或运行期失败不会自动切换 |
| `QDRANT_URL` | 空时使用两个本地 Qdrant 目录 | 被商品检索用例捕获的向量异常或空候选降级为关键词召回；工具级超时/取消不保证降级。品类知识建库失败后工具仍注册，后续检索可能成功、返回空结果或返回错误，没有替代 RAG 降级链 |
| `RERANKER_BASE_URL` | 空时不创建 reranker | 向量召回后按向量分排序 |
| `TAVILY_API_KEY` | 空时不注册工具 | Agent 看不到 `web_search_tool` |
| `REDIS_URL` + `QUEUE_ENABLED` | 两者同时生效才创建队列 | 未配置 Redis 时 API 直跑；已配置但 Redis 不可达时不会自动切回直跑 |
| `HARNESS_ENABLED`、`OUTPUT_GUARD_ENABLED` | 默认开启 | 只覆盖实际接线的位置，不能视为全工具安全保证 |
| `DRIFT_DETECT_ENABLED`、`TOKEN_BUDGET_TOTAL`、`BREAKER_SHARED`、`PREFERENCE_RELEVANCE_ENABLED` | 默认关闭 | 必须显式开启；未开启时对应漂移、请求级预算、共享熔断和相关性筛选不生效 |

完整默认值和环境变量解析以 [settings.py](../app/infrastructure/settings.py#L94) 为准，`.env.example` 只列出常用子集，不是完整配置清单。

运行模式还存在三组需要联动考虑的约束：

- 队列模式会同时运行 API 与 worker；若 `QDRANT_URL` 仍为空，两类进程会尝试打开同一 `DATA_DIR/qdrant` 和 `qdrant_kb` 本地目录。本地嵌入模式适合单进程开发，多进程应配置服务端 Qdrant，见 [qdrant_product_index.py](../app/infrastructure/vector/qdrant_product_index.py#L26) 和 [category_knowledge.py](../app/infrastructure/rag/category_knowledge.py#L34)。
- 默认 SQLite 虽启用了 WAL 和 5 秒 busy timeout，但 API 与一个或多个 worker 仍共享同一数据库文件；高并发写入仍可能出现锁竞争，代码不会自动切换到服务型数据库，见 [repositories.py](../app/infrastructure/persistence/sql/repositories.py#L56)。
- worker 无条件调用 `loop.add_signal_handler()` 注册 `SIGTERM`/`SIGINT`；该 API 在 Windows 默认 Proactor event loop 上不受支持，因此当前 worker 入口应按 Linux / Docker 运行，或先增加跨平台信号处理，见 [worker.py](../app/worker.py#L47)。

### 6.2 验证入口

| 范围 | 入口 | 说明 |
| --- | --- | --- |
| 单元与基础设施测试 | `tests/` | 领域规则、检索、存储、缓存、队列、护栏和偏好等 |
| 商品 / 品类召回 | `scripts/eval/run_product_recall.py`、`run_category_recall.py` | 使用 `eval/*.jsonl` 做确定性召回指标 |
| 评测数据校验 | `scripts/eval/validate_datasets.py` | 校验评测 JSONL 的结构、标识引用与基础字段 |
| Agent 行为回归 | `scripts/eval_regression.py` | 需要已启动服务与模型；应关闭语义缓存，避免评分命中旧回复 |
| 端到端冒烟 | `scripts/smoke_e2e.py` | 人工观察 HTTP 最终结果和 WebSocket 事件数量；脚本主要打印结果，没有系统断言两者一致或必需事件齐全 |
| 并行与容量 | `scripts/verify_parallel.py`、`loadtest.py`、`locustfile.py` | 分别观察单意图内并行和多意图压力；`verify_parallel.py` 没观察到重叠也不一定失败退出，脚本存在不等于当前环境已经通过 |

现有测试覆盖了较多领域规则和使用 Fake/Mock 的基础设施行为，但仓库中未找到 `build_app()` REST 路由、WebSocket `ConnectionManager`、`MainAgentOrchestrator.handle_intent()`、`worker.main()`、`claim_stale()`、真实 Redis pending/PubSub，以及同 session、多 worker 并发竞态的完整接线测试。因此本节列出的入口不能被当作这些运行时边界已经通过集成验证的证明。

## 7. 目录地图

```text
globex-agent/
├── app/
│   ├── composition.py             # API / worker 共用的组装根
│   ├── worker.py                  # Redis Stream 消费进程
│   ├── presentation/              # FastAPI、DTO、WebSocket
│   ├── application/
│   │   ├── agents/                # Agent factory、Orchestrator、SessionRegistry
│   │   ├── tools/                 # 模型可调用的业务工具
│   │   ├── usecases/              # 商品与订单应用流程
│   │   ├── prompts/               # 主/子 Agent Prompt
│   │   ├── memory/                # 偏好筛选
│   │   └── harness/               # 断言、循环与漂移检测
│   ├── domain/                    # 领域对象、规则和端口
│   └── infrastructure/            # LLM、检索、存储、Redis、治理与安全
├── frontend/                      # React + Vite 前端
├── knowledge/                     # 品类知识 Markdown
├── eval/                          # 评测数据
├── scripts/                       # 冒烟、评测、并行与压测脚本
├── tests/                         # 单元和基础设施测试
├── docker/                        # Docker Compose
└── review/                        # 源码学习文档
```

## 8. 建议阅读顺序

| 顺序 | 文件 | 先回答的问题 |
| --- | --- | --- |
| 1 | [App.tsx](../frontend/src/App.tsx) | 请求从哪里发出，结果如何显示？ |
| 2 | [server.py](../app/presentation/server.py) | HTTP、WebSocket 和队列在哪里分叉？ |
| 3 | [composition.py](../app/composition.py) | 当前实际装配了哪些实现？ |
| 4 | [orchestrator.py](../app/application/agents/orchestrator.py) | 每次意图固定经过哪些阶段？ |
| 5 | [main_agent.py](../app/application/agents/main_agent.py) | MainAgent 有哪些工具和状态？ |
| 6 | [globex.yml](../app/application/prompts/globex.yml) | 模型被怎样约束选择工具？ |
| 7 | [catalog_search.py](../app/application/usecases/catalog_search.py) | 商品检索如何召回、降级和过滤？ |
| 8 | [task_dispatch_tool.py](../app/application/tools/task_dispatch_tool.py) | 子 Agent 如何创建及隔离上下文？ |
| 9 | [order_usecases.py](../app/application/usecases/order_usecases.py) | 下单/取消改变了什么数据？ |
| 10 | [llm.py](../app/infrastructure/llm.py) | 模型限流、重试、回退和预算在哪里发生？ |
| 11 | [eventbus.py](../app/infrastructure/eventbus.py) | 事件如何到达 WebSocket？ |
| 12 | [repositories.py](../app/infrastructure/persistence/sql/repositories.py) | 会话、对话、订单和偏好如何落库？ |
