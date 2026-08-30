# Day 8：测试、优化、二次开发与简历表达

## 1. 先建立测试金字塔

当前仓库包含 37 个 Go 测试文件、52 个 Cypress spec（Cypress 端到端测试规格文件）和 30 个 Vitest 风格的前端单元测试文件，共 82 个前端测试文件。测试类型包括：

### 单元测试

适合纯规则和边界：

- Automation 条件组合。
- Authz 分配规则。
- AI Provider 参数适配、Token/Embedding Batch、Tag Index、Tool Secret、Prompt 边界和 OTP 状态机。
- WebSocket（全双工长连接协议）map/订阅并发行为。
- 字符串和附件处理。

例如 [`internal/automation/evaluator_test.go`](../../internal/automation/evaluator_test.go) 用 mock（模拟依赖）Conversation Store 验证 AND/OR（逻辑与/逻辑或）、短路和 first-match（首个匹配即停止）。

测试要和生产入口配对阅读：[`authz_test.go`](../../internal/authz/authz_test.go) 证明权限组合，[`automation/suppress_test.go`](../../internal/automation/suppress_test.go) 证明循环抑制，[`conversation/message_test.go`](../../internal/conversation/message_test.go) 主要证明 HTML/CID 边界。它们不能自动证明所有路由都接入授权、队列关闭安全或完整 outgoing Worker 状态机。读测试时应先写清楚 mock 掉了什么。

### 数据库集成测试

Makefile 提供临时 PostgreSQL：

```powershell
make test-db
go test -count=1 ./...
make test-db-down
```

集成测试应该验证事务、唯一约束、SQL 行锁和并发更新；这些行为无法被纯 mock 真实覆盖。

数据库辅助函数是 [`testutil.NewDB`](../../internal/testutil/testutil.go#L24-L61)。它默认连接 `127.0.0.1:5433`，不可达时执行 `t.Skipf`，随后才创建 `libredesk_test_<name>` 并应用 `schema.sql`。因此 `go test ./...` 返回 PASS 只证明未跳过路径通过，必须用下面的 verbose 输出检查 `SKIP`：

```powershell
go test -count=1 -v ./internal/sla ./internal/user
```

[`sla_test.go`](../../internal/sla/sla_test.go) 和 [`contact_test.go`](../../internal/user/contact_test.go) 只有在 PostgreSQL 真正可达时，才构成数据库约束、事务和并发证据。测试 DSN 只能指向隔离实例，因为辅助代码会创建并删除测试数据库。

当前提交 `3dccdb4b` 的本地复核结果是：`go vet ./...` 通过，`go test -count=1 ./...` 以退出码 0 完成；但详细执行 `go test -count=1 -v ./internal/sla ./internal/user` 时有 49 个数据库用例因 `127.0.0.1:5433` 拒绝连接而 `SKIP`。所以这份快照只能记为“静态检查和非数据库路径通过，数据库集成覆盖不完整”，不能写成后端完整测试通过。

### API（应用程序编程接口）/E2E（端到端）测试

[`frontend/cypress/e2e/api/conversations.cy.js`](../../frontend/cypress/e2e/api/conversations.cy.js) 覆盖创建、查询、状态、分配、标签等 API；Live Chat 测试覆盖 Widget 初始化、双向消息和 WebSocket 更新。

E2E 能验证系统拼装正确，但运行慢、失败定位困难，不应替代单元和集成测试。

## 2. 一次后端改动的最低验证集

```powershell
# 格式和静态检查
gofmt -w <changed-go-files>
go vet ./...

# 单元/集成测试
go test -count=1 ./...

# 并发相关改动
go test -race ./internal/ws ./internal/automation ./internal/conversation

# AI/Agent 相关改动
go test -count=1 ./internal/ai/... ./internal/aiagent/...
go test -race ./internal/ai/... ./internal/aiagent/...

# 前端/API 回归（需要完整环境）
cd frontend
pnpm test:run
pnpm test:e2e:ci
```

`-race` 不是性能测试，而是动态数据竞争检测（检查多个协程未同步读写同一内存）；只有执行到的路径才能被检查。

上述命令只是建议的验证层级，不代表当前所有包都能在任意机器无依赖通过。数据库集成测试会读取测试 DB 配置，Cypress 还需要应用、前端预览及相应依赖服务；提交前应记录实际执行环境、跳过项和失败项，不能只贴一组未运行的命令。

Mock 可以证明调用决策，但不能证明 PostgreSQL 锁、SMTP 回执、Redis 原子性或网络超时。并发相关修改还应执行 `go test -count=1 -race ./internal/ws ./internal/conversation ./internal/automation ./internal/aiagent`；race detector 同样只能检查实际走到的路径。

## 3. 如何设计一条高价值测试

以“消息发送”为例，不只测试 200：

```text
Given：存在可用 Inbox、Conversation 和有权限 Agent
When：发送一条带附件的客服回复
Then：
  - 返回 pending Message
  - Message 和附件在一个事务中关联
  - Conversation 快照更新
  - Worker 投递后 status=sent
  - 渠道失败后 status=failed
  - 只有本人失败消息能 Retry
  - 重启扫描仍能发现 pending
  - 无权限 Agent 无法发送或订阅
```

高价值测试覆盖的是业务不变量和故障窗口，而不是追求行覆盖率数字。

数据访问错误路径也要单独测。当前 `GetConversationMessages` 和 `GetConversations` 在检查 `BeginTxx` 错误前注册 `defer tx.Rollback()`；应让数据库或可替换的 Begin 函数返回 `(nil, error)`，断言接口返回统一错误且没有 panic。正常数据库集成测试很难自然走到这个分支，所以“成功路径覆盖率很高”也不能替代明确的故障注入。

以“自主 AI Assistant 回复”为例，也不能只 Mock 一个非空模型答案：

```text
Given：Conversation 分配给 Enabled Assistant，Completion/Embedding Provider 可控
When：主 Contact 发送一条需要知识和受验证 Tool 的消息
Then：
  - 同 Conversation 同时只运行一个 Worker
  - Knowledge Search 低于阈值时不凭模型常识回答
  - 未验证时绝不发出业务 Tool HTTP 请求
  - OTP 成功后同一 Tool Loop 能重试业务 Tool
  - 人工中途接管后不 Queue AI Reply/Resolve
  - 正常回答仍进入统一 pending -> sent/failed 消息链
  - Resolve 一定晚于最终 Reply 入队
  - Queue 满、超时或空答案最终进入 Human Handoff
```

更多 Agent 测试空白和故障实验见 [Day 7](07-ai-agent-deep-dive.md#19-测试现状哪些结论有自动化证据)。

## 4. 性能分析顺序

不要先改代码。推荐顺序：

1. 定义症状和 SLO，例如会话列表 P95 < 200ms。
2. 构造接近真实的数据量。
3. 用 pprof、日志和 SQL Explain 找证据。
4. 只改变一个变量。
5. 重复压测并记录前后数据。
6. 增加回归测试或基准。

项目可通过配置启动 pprof，入口在 [`cmd/pprof.go`](../../cmd/pprof.go)。数据库重点查看：

```sql
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT ...;
```

关注：Seq Scan、实际行数与估算行数差距、Sort 是否落盘、循环次数、Buffer Hit/Read，而不是只看总耗时。

例如优化 pending 扫描，应把 [`get-outgoing-pending-messages`](../../internal/conversation/queries.sql#L697-L738) 的执行计划、一次返回行数、channel 容量、Worker 数、oldest pending age、连接池等待和渠道发送耗时放在同一份基线中；单个函数 benchmark 不能证明端到端积压改善。

## 5. 八天主线后最适合做的二次开发

从下面选一个，范围控制在 1～3 天可完成。

### 方案 A：Webhook 持久化重试

新增 delivery 表与状态机：

```text
pending -> processing -> delivered
                    -> retry_wait -> processing
                    -> dead
```

字段可包含 event（事件）、payload（事件负载）、webhook_id、attempts（尝试次数）、next_retry_at、last_error、lease_until（租约到期时间）。价值：事务、Worker（工作协程）、多实例、退避、幂等、可观测性都能讲。

### 方案 B：多实例安全的消息抢占

将 pending（待处理）扫描改为事务内批量 claim（任务领取），使用 `FOR UPDATE SKIP LOCKED`（加行锁并跳过已锁行）、processing（处理中）状态和 lease（任务租约）。补充两个 Manager 并发抢占的集成测试。

### 方案 C：慢 SQL 优化

准备大数据量，选 Conversation List 或 Pending Scan，记录 Explain，通过复合/部分索引或 SQL 改写优化。必须保留前后执行计划与 P95 数据。

### 方案 D：可观测性

为消息、Webhook 或 AI Worker 增加：

- queue length
- enqueue drop count
- processing duration
- success/failure/retry count
- external call duration

如果引入 Prometheus，需要同时考虑指标标签基数，不能把 conversation UUID 当 label。

### 方案 E：AI Agent 可恢复执行与竞态测试

先不要直接引入复杂工作流引擎。可以先完成一个有边界的改进：

- 为 Conversation Run 增加持久 Job 或基于最新 Incoming Message 的补扫。
- 用 DB/Redis Lease 保证双实例只有一个 Run 获得发送资格。
- 为外部 Custom Tool 传稳定 Idempotency Key。
- 增加 Queue Full、Worker Panic、Mid-run Takeover、Shutdown 和双实例测试。
- 记录 queue depth、run duration、tool latency、handoff reason 和 dropped/stale run。

价值：能同时讲 Agent、并发、幂等、外部副作用、故障恢复和可观测性。范围必须控制在一个可验证的不变量，不能只写“升级为分布式 Agent 平台”。

## 6. 设计文档模板

在动手改代码前写一页：

```markdown
# 问题
用户可观察到什么？源码证据是什么？

# 当前链路
入口、数据状态、副作用、失败行为。

# 目标与非目标
明确这次修改不解决什么。

# 方案
表结构、状态机、接口、并发与回滚。

# 风险
兼容性、数据迁移、重复执行、性能、安全。

# 验证
单元、集成、并发、故障注入、性能数据。
```

## 7. 代码评审清单

- Handler 是否只做协议适配，没有复制领域规则？
- 是否同时检查动作权限和资源权限？
- SQL 是否参数化？动态片段是否来自白名单？
- 事务是否覆盖必须原子完成的数据操作？
- 外部 HTTP 是否有 Context（上下文）、Timeout（超时）、响应大小限制和 SSRF（服务端请求伪造）防护？
- Worker 是否处理队列满、panic、关闭和重复执行？
- 日志是否包含定位 ID，但不包含密钥和敏感正文？
- 新状态是否可从崩溃中恢复？
- 多实例下是否仍然正确？
- 测试是否验证失败路径和业务不变量？
- 日志、指标、追踪是否会泄漏 Token（令牌）、消息正文、联系人 PII（个人可识别信息）或 AI prompt（人工智能提示词）？
- migration 是否支持已有脏数据、滚动升级和回滚/前滚？
- 限流、分页、批处理和队列是否有明确上限，Redis/DB 故障时是 fail-open 还是 fail-closed？

## 8. 简历项目定位

项目名称建议：

> LibreDesk 开源客服系统源码研读与二次开发

技术栈：

> Go、fasthttp、PostgreSQL、Redis、WebSocket、Vue 3、Docker；扩展模块包括 Automation（自动化）、SLA（服务等级协议）、Webhook（事件回调）和 AI/RAG（人工智能/检索增强生成）。

在没有真实改动前，只能写：

- 独立部署并梳理模块化单体架构，追踪认证、会话、消息异步投递和 WebSocket 实时推送链路。
- 分析 PostgreSQL 数据模型、事务边界、数据库持久化队列及 Worker Pool（工作协程池）的可靠性语义。
- 完成 Automation、SLA、Webhook 与 AI/RAG 扩展机制的源码分析和故障推演。
- 深入追踪 OpenAI-compatible Provider、内存 RAG、Copilot 与自主 AI Assistant 的 Tool Calling、OTP、Handoff 和 FAQ 学习链路，区分持久化业务状态与进程内 Agent Run。

完成二次开发后，用数据替换空泛描述，例如：

> 为 Webhook 投递设计持久化任务状态机与指数退避机制，支持进程重启恢复和失败重放；补充并发集成测试，在故障注入场景下验证无任务静默丢失。

或者：

> 将消息扫描改造为基于 PostgreSQL `FOR UPDATE SKIP LOCKED` 的租约抢占，消除双实例并发重复领取；通过集成测试验证崩溃恢复和租约过期重领。

不能把未经验证的“高并发”“性能提升 80%”“零消息丢失”写进简历。

## 9. 项目面试的四段式回答

### 业务

“这是一个自托管全渠道客服系统，把邮件和 Live Chat 统一为 Conversation/Message 模型。”

### 架构

“Go 模块化单体承载 HTTP、WebSocket 和 Worker，PostgreSQL 保存业务状态，Redis 保存 Session、缓存和临时状态。”

### 深入点

“我重点研究并改造的是消息链路：HTTP 先写 pending，后台 Worker 扫描投递，状态更新后触发实时广播和扩展事件。”

### 权衡与改进

“数据库队列部署简单并能崩溃恢复，但进程内去重不适合多实例，外部发送也存在重复窗口；我用租约抢占/幂等/Outbox（事务发件箱）中的某一种做了实际改进并通过测试验证。”

## 10. 八天验收题

不看文档，连续回答：

1. 启动时 Manager 和 Worker 的顺序是什么？
2. Session（登录会话）、API Key（接口访问密钥）、CSRF（跨站请求伪造防护）、RBAC（基于角色的访问控制）、资源授权分别解决什么问题？
3. Message 与 Conversation 表为什么同时保存消息信息？
4. `InsertMessage` 的事务边界在哪里？为什么 Webhook 不在事务里？
5. pending 消息在什么故障下能恢复，在什么故障下会重复？
6. WebSocket 如何处理慢客户端和权限？
7. Automation 如何防止循环？
8. SLA 为什么需要 applied_slas 和 sla_events 两层？
9. 内存向量索引的优势和扩展上限是什么？
10. `internal/ai`、Copilot 与 `internal/aiagent` 的职责边界是什么？
11. Agent 为什么把 Contact 身份放在服务端 ToolContext，而不允许模型提供？
12. 人工接管检查为什么不能撤销已经执行的外部 Tool 副作用？
13. OTP、Handoff、Resolve 和 FAQ Review 分别保护哪个业务不变量？
14. 你的二次开发解决了什么可验证的问题？
15. 如果面试官要求双实例部署，你会先阻止哪些后台任务重复执行？
16. 如果 Redis、PostgreSQL、SMTP（简单邮件传输协议）、对象存储、AI Provider 分别故障，用户看到的现象和恢复路径是什么？

能用源码函数、表结构和测试证据回答这些问题，就已经达到“完成八天主线后比较深入”的目标。
