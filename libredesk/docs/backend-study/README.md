# LibreDesk 后端源码：8 天深度学习手册

> 适用目标：每天约 3 小时，用 8 天建立对一个真实互联网后端项目的整体认识，并形成可用于简历和面试的技术材料。其中 AI/Agent 是独立必修主线，不再作为高级模块中的可选小节。
>
> 文档依据：本地源码提交 `3dccdb4b`（2026-08-30 复核）。源码继续演进后，行号可能变化，应优先按函数名搜索。
>
> 复核范围：本文档不把源码注释当作最终事实；结论同时对照了 Handler（请求处理函数）、Manager（领域业务管理器）、SQL（结构化查询语言）、Schema（数据库结构定义）、配置与测试。跨模块的生产风险、业务场景和面试追问集中在[源码审查与场景深挖](09-production-review-and-interview.md)。

当前源码快照包含 243 个 Go 文件、37 个 Go 测试文件、50 张数据库表、374 条命名 SQL 和约 274 个后端路由注册点。这个规模适合先按业务调用链建立地图，再进入单个 CRUD（增、查、改、删）函数；逐文件平铺阅读会很快失去上下文。

## 1. 八天结束时应达到什么程度

不是“把所有文件看一遍”，而是能够独立讲清楚下面这条业务链：

```text
客服登录
  -> 请求经过认证、CSRF（跨站请求伪造防护）和 RBAC（基于角色的访问控制）
  -> 查询或创建 Conversation（会话）
  -> 客服发送 Message（消息），先以 pending（待处理）状态写入 PostgreSQL
  -> 后台 Worker（工作协程）扫描并投递到 Email / Live Chat（邮件 / 在线聊天）
  -> 消息状态更新为 sent / failed（已发送 / 失败）
  -> WebSocket（全双工长连接协议）推送坐席端和访客端
  -> Automation（自动化）、SLA（服务等级协议）、Webhook（事件回调）和通知等旁路机制按具体事件和分支触发
  -> 若会话分配给 AI Assistant，事件进入 Agent Worker，完成 RAG、工具调用、自动回复或转人工
```

学完后应能回答：

1. LibreDesk 为什么是模块化单体，而不是微服务？
2. HTTP Handler、Manager、SQL 文件分别承担什么职责？
3. Session、API Key（接口访问密钥）、CSRF 和 RBAC 如何配合？
4. 为什么发送消息要先落库，再由 Worker 投递？
5. 服务重启后，尚未发送的消息为什么还有机会恢复？
6. 当前消息机制在多实例部署下可能遇到什么问题？
7. WebSocket 如何管理连接、订阅、心跳、慢客户端和并发关闭？
8. Automation 如何避免动作再次触发自身造成循环？
9. SLA、Webhook 和 AI（人工智能）/RAG（检索增强生成）如何挂接到核心会话领域？
10. Provider、RAG、Copilot 与自主 AI Assistant 分别承担什么职责？
11. Agent 如何限制工具权限、验证联系人身份，并避免覆盖人工接管？
12. 如果要把项目用于简历，哪些内容可以诚实地写成自己的成果？

## 2. 八天阅读顺序

| 天 | 主题 | 必读文档 | 3 小时产出 |
|---|---|---|---|
| Day 1 | 架构、启动、依赖装配 | [01-架构与启动](01-architecture-and-startup.md) | 一张启动时序图；能解释所有基础设施 |
| Day 2 | HTTP、认证、授权 | [02-HTTP 与权限](02-http-auth-and-rbac.md) | 手工追踪登录和会话查询接口 |
| Day 3 | 领域模型、表结构、SQL | [03-领域与数据](03-domain-data-and-sql.md) | 核心 ER 图；解释索引和事务边界 |
| Day 4 | 消息收发主链路 | [04-消息流水线](04-message-pipeline.md) | 画出 outgoing/incoming 两条时序图 |
| Day 5 | 并发、WebSocket、可靠性 | [05-并发与实时通信](05-concurrency-and-websocket.md) | 列出 5 个并发或可靠性风险 |
| Day 6 | 自动化、SLA、Webhook 与 AI 总览 | [06-高级模块](06-platform-and-ai.md) | 比较四类异步扩展的可靠性语义 |
| Day 7 | Provider、RAG、Copilot、自主 Agent | [07-AI 与 Agent 深入](07-ai-agent-deep-dive.md) | 画出 Agent Run、Tool/OTP 和 FAQ 三条完整链路 |
| Day 8 | 测试、优化、简历与面试 | [08-验证与简历](08-testing-optimization-and-resume.md) | 一个真实改进方案和一版项目表述 |

八天完成后，再用[源码审查与场景深挖](09-production-review-and-interview.md)做横向复盘。它不是“Day 9”，而是把认证、事务、队列、多实例、可观测性、容量和业务故障串成一套面试深挖框架。

## 3. 每天固定的三小时节奏

建议每天都按同一节奏执行：

- 0:00～0:20：回顾昨天的图和结论，不看文档口述一遍。
- 0:20～1:20：按文档给出的入口阅读源码，只追一条调用链。
- 1:20～2:10：运行系统、打断点、查看日志、调用接口或执行 SQL。
- 2:10～2:40：回答当天的“必须回答”问题。
- 2:40～3:00：形成一页笔记，记录证据、疑问和改进点。

阅读一个函数时使用统一模板：

```text
入口：谁调用它？HTTP、WebSocket、定时器还是另一个 Manager？
输入：输入从哪里来，在哪里校验？
权限：认证和资源级授权在哪里发生？
数据：读写哪些表，事务边界在哪里？
副作用：是否发消息、广播、通知、Webhook 或调用外部服务？
失败：失败如何返回、记录、重试或补偿？
并发：多个 goroutine / 进程同时执行是否安全？
扩展：数据量或实例数增长后，首先出现什么瓶颈？
```

## 4. 本地运行基线

项目开发环境至少需要：

- Go 1.25（以 `go.mod` 为准）
- PostgreSQL 17
- Redis 7
- Node.js 20.19+、pnpm 9.15.3（只在调试前端时需要；Node 下限来自当前 Vite 依赖，pnpm 版本来自 `frontend/package.json`）

仓库现有本地启动记录：

```powershell
# 后端
go run ./cmd/ --config config.dev.toml

# 前端，在 frontend 目录执行
pnpm dev:main
```

生产式依赖可以参考根目录 `docker-compose.yml`。应用默认监听 `9000`，PostgreSQL 和 Redis 只绑定本机地址。

第一次启动前应先确认数据库已经安装 schema。应用支持：

```powershell
go run ./cmd/ --config config.dev.toml --install
go run ./cmd/ --config config.dev.toml --set-system-user-password
```

不要在已有数据的数据库上随意执行安装或升级命令。学习环境最好使用独立数据库。

## 5. 推荐的调试方式

### 用日志定位调用链

`config.dev.toml` 已将日志级别设为 `debug`。先在浏览器完成一次动作，再按关键字搜索：

- `message_id`
- `conversation_uuid`
- `inbox_id`
- `error sending message`
- `automation`
- `webhook`
- `ai agent handling conversation`
- `ai run step`
- `rag search`

`debug` 日志可能包含 Webhook payload、AI system prompt、模型输出、工具参数或工具结果，不能把生产日志直接复制到公开 issue 或面试材料中；当前 `middlewares.go` 的 CSRF mismatch 日志还会记录 cookie/header token，这是应优先修正的敏感信息泄漏点。

### 用断点验证，而不是靠猜

发送一条客服回复时，建议依次在这些函数设置断点：

1. `handleSendMessage`
2. `conversation.Manager.QueueReply`
3. `conversation.Manager.InsertMessage`
4. `conversation.Manager.Run`
5. `conversation.Manager.sendOutgoingMessage`
6. `conversation.Manager.UpdateMessageStatus`

### 用数据库验证状态

```sql
SELECT id, uuid, status, type, sender_type, created_at
FROM conversation_messages
ORDER BY id DESC
LIMIT 20;

SELECT id, uuid, status_id, assigned_user_id, assigned_team_id,
       last_message, waiting_since, first_reply_at, last_reply_at
FROM conversations
ORDER BY id DESC
LIMIT 20;
```

观察重点不是数据内容，而是一次业务操作到底改变了哪些状态。

## 6. 学习边界

八天内暂时跳过：

- 前端组件细节和样式系统；AI/Agent 只追产品入口、状态隔离和 API 调用，不逐行学习 CSS。
- 每一个 CRUD（增、查、改、删）模块；Tag、Template、View 等只在需要对照模式时阅读。
- 每一条 SQL；先掌握 Conversation、Message、User、Inbox、SLA 五组核心表。
- Agent 不在跳过范围：Provider、RAG、Copilot、自主 Assistant、Tool/OTP、FAQ、API/RBAC、并发和测试边界都要完成 [Day 7](07-ai-agent-deep-dive.md)。
- 所有迁移历史；先理解 `schema.sql`，再抽样看一个 migration（数据库迁移脚本）。

## 7. 这一套文档如何用于面试准备

每篇文档都区分三类内容：

- **源码事实**：可以由当前代码直接验证。
- **技术解释**：把源码映射到通用后端知识。
- **工程判断**：基于源码作出的权衡和风险分析，需要在面试时说明这是分析而不是原作者结论。

简历中应写“开源项目源码研读、独立部署、二次开发或贡献”，不要把整个 LibreDesk 描述成自己从零开发。只有亲手完成并验证的修改，才能写成自己的实现和优化。

## 8. 结论可信度怎么标注

复盘时给每条结论加一个标签，避免把推演说成已经发生的事故：

- `事实`：能由当前函数、SQL、Schema 或测试直接证明。
- `风险`：源码存在故障窗口，但尚无压测或线上事故数据证明它已经造成影响。
- `方案`：候选改造，需要说明代价、迁移和验证方式，不能说成项目现状。
- `待验证`：必须通过运行、故障注入、`EXPLAIN`（SQL 执行计划分析）、race detector（数据竞争检测器）或双实例实验才能下结论。

面试时最可靠的表达顺序是“源码事实 → 故障窗口 → 业务影响 → 方案权衡 → 验证证据”。
