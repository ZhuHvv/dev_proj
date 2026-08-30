# LibreDesk Redis、Session、Cache 与 Rate Limit 源码学习

## 1. 这个模块在 LibreDesk 中解决什么问题

[上一章](06-websocket-realtime-l4.md)强调 WebSocket registry 是进程内状态；本章转向跨请求、跨实例共享的 Redis，并回扣[HTTP 认证与授权](04-http-auth-authorization-api-layer-l4.md)。Session、可重建页面缓存和共享限流计数虽然共用 Redis，却有不同的 Key、TTL（存活时间）、一致性要求和故障后果。

## 本章核心源码

| 优先级 | 文件 / Symbol | 为什么必须读 |
|---|---|---|
| P0 | [`SaveSession` → `internal/auth/auth.go:259`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:259:1) | 后台身份如何写入 Redis 并设置 Cookie |
| P0 | [`ValidateSession` → `internal/auth/auth.go:342`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:342:1) | 请求如何从 Session 恢复 User |
| P0 | [`generateSessionToken` → `cmd/chat.go:954`](vscode://file/D:/codes/dev_proj/libredesk/cmd/chat.go:954:1) | Widget Token、Session Hash 与反向索引的建立 |
| P0 | [`cacheHCPage` → `cmd/helpcenter.go:1135`](vscode://file/D:/codes/dev_proj/libredesk/cmd/helpcenter.go:1135:1) | Help Center 旁路缓存的命中与回填 |
| P0 | [`clearsHCCache` → `cmd/helpcenter.go:1171`](vscode://file/D:/codes/dev_proj/libredesk/cmd/helpcenter.go:1171:1) | 数据修改后的缓存失效 |
| P0 | [`Limiter.Check` → `internal/ratelimit/ratelimit.go:40`](vscode://file/D:/codes/dev_proj/libredesk/internal/ratelimit/ratelimit.go:40:1) | 有序集合（Sorted Set）滑动窗口与故障放行（Fail-open）行为 |
| P1 | [`initRedis` → `cmd/init.go:926`](vscode://file/D:/codes/dev_proj/libredesk/cmd/init.go:926:1) | Redis Client 的配置、注入与生命周期 |

## 2. 一张图看懂整体机制

```text
登录 → 后台 Session Key ──TTL──→ 恢复 Agent 身份
Widget token → Widget Session Key ──TTL──→ 恢复访客与 Inbox
DB 查询 → Help Center Cache → 命中直接返回 / 写后失效
请求维度 → Redis 计数 → 时间窗口内允许或拒绝
```

## 3. 必须先理解的核心概念

- **TTL（Time To Live，存活时间）**：Key 在 Redis 中自动过期前可存在的时长。
- **滑动过期（Sliding Expiration）**：每次有效访问都续期；必须从读路径是否执行续期判断，不能只看到 TTL 就下结论。
- **旁路缓存（Cache-aside）**：业务先查缓存，未命中再查 DB 并回填；写操作通常先改 DB，再删除或刷新缓存。
- **限流（Rate Limiting）**：按 IP、用户或业务标识统计时间窗口内请求数，超限时拒绝，保护资源和防止滥用。
- **流水线（Pipeline）**：把多条 Redis 命令批量发送以减少网络往返；普通 Pipeline 不等于 `MULTI/EXEC` 事务。
- **故障放行（Fail-open）**：保护性依赖失败时继续允许业务请求；当前限流在 Redis `Exec` 出错时采用该策略。

## 4. 源码阅读路线

**后台 Session：** [`SaveSession`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:259:1) → [`ValidateSession`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:342:1) → [`DestroySession`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:376:1)。

**Widget Session：** [`generateSessionToken`](vscode://file/D:/codes/dev_proj/libredesk/cmd/chat.go:954:1) → [`loadSession`](vscode://file/D:/codes/dev_proj/libredesk/cmd/chat.go:980:1) → [`deleteSessionToken`](vscode://file/D:/codes/dev_proj/libredesk/cmd/chat.go:1011:1)。

**限流：** [`Limiter.Check`](vscode://file/D:/codes/dev_proj/libredesk/internal/ratelimit/ratelimit.go:40:1)。


## 5. 先区分 Redis 的三类业务职责

### Client 的创建、注入与关闭

`cmd/init.go:initRedis` 只用 `redis.url`，或 `redis.address/user/password/db` 构造一个 `*redis.Client`。`cmd/main.go:main` 把同一个 Client 注入：

1. `internal/auth.Auth`：后台 Agent/OIDC Session；
2. `internal/aiagent.Manager`：OTP（一次性验证码）状态和发送次数；
3. `internal/ratelimit.Limiter`：HTTP 按 IP 限流；
4. `fastcache` 的 `goredis.Store`：Help Center HTML/Markdown 响应缓存；
5. `App.redis`：Widget Session、Inbox OAuth 状态、页面访问、文章反馈去重。

退出时 `cmd/main.go:main` 在 HTTP、Worker、DB 等组件停止后调用 `rdb.Close()`。`initRedis` 本身没有 `PING`，Client 构造也是惰性连接，因此源码不能证明“Redis 不可达会阻止服务启动”。

LibreDesk 的非 URL 配置没有显式设置超时或重试。`go-redis/v9@v9.5.5` 的 `Options.init` 会补默认值：Dial 5 秒、Read 3 秒、Write 跟随 Read、连接池等待 4 秒、命令最大重试 3 次。若 `redis.url` 自己携带对应参数，则以解析结果为准。

### 真实用途总表

| 用途 | 入口 / 核心 Symbol | Redis 数据类型 | 是否跨实例 | 故障取向 |
|---|---|---:|---:|---|
| 后台 Agent Session | `auth.Auth` / `SaveSession` / `ValidateSession` | Hash | 是 | 登录失败；受保护请求认证失败 |
| Widget Session | `generateSessionToken` / `loadSession` | Hash + String 反向索引 | 是 | 创建失败；校验失败；TTL 刷新失败被忽略 |
| Help Center 响应缓存 | `cacheHCPage` / `clearsHCCache` | 分组 Hash | 是 | 读写/失效失败均降级，不阻断业务 |
| HTTP Rate Limit | `ratelimit.Limiter.Check` | Sorted Set（有序集合） | 是 | Redis 错误时 fail-open（放行） |
| 文章反馈去重 | `handleHelpCenterArticleFeedback` | String，`SET NX` | 是 | Redis 错误时继续写 DB |
| Widget 页面访问 | `handleWidgetPageVisit` / `getPageVisitsFromRedis` | List | 是 | 错误静默降级为空/不广播 |
| Inbox OAuth 临时状态 | `handleOAuthAuthorize` / `handleOAuthCallback` | Hash | 是 | 写/读失败使 OAuth 流程失败 |
| AI Agent OTP | `otp.go` + `tools.go` | String/JSON/Counter | 是 | 验证 fail-closed；发送链部分错误上传播 |

【代码分析】该 Client 并非单纯“缓存连接”。它同时承载认证状态、限流状态、安全验证状态和可丢弃缓存。因此“Redis 整体故障”不会形成一种统一结果，而会按调用点分别表现为 401/500、功能降级、限流放行或验证拒绝。

---

### Key、TTL 与生命周期总览

| 业务用途 | Key | Value | Write / Read | TTL | Update / Invalidate |
|---|---|---|---|---|---|
| 后台 Session | `session:<64位随机字母数字ID>` | Hash：`_ss=1`，以及 `id/email/first_name/last_name`；OIDC 临时会话还有 `oidc_state/oidc_next` | `NewSession` + `SetMulti` / `GetMulti` | `app.server.session_lifetime`，默认 9h | 固定 TTL，不随读写刷新；`Destroy` 删除整个 Key |
| Widget Session | `widget_session:<43字符Base64URL token>` | Hash：`user_id/inbox_id/is_visitor/external_user_id` | `HSET+EXPIRE` / `HGETALL` | 访客固定 180d；Contact 为 inbox `session_duration`，空、非法或 `<1h` 回退 180d | 每次成功读取后尝试 `EXPIRE` 滑动续期；合并访客后删除访客 token |
| Widget 反向索引 | `widget_user:<inboxID>:<contactID>` | session token | `SET` / `GET` | 同 Contact Session | Auth exchange 时复用或覆盖；没有和正向 Hash 原子更新 |
| Help Center 页面 | `libredesk:cache:hc:helpcenter` | Hash；每个 URI 摘要对应 `_ctype_/_etag_/_compression_/_blob_` 四个 field | `HMGET` / `HMSET+PEXPIRE` | 整个分组 30m | 成功管理写请求后 `DEL` 整组 |
| HTTP 限流 | `rate_limit:<rule>:<clientIP>` | ZSet：score=Unix 秒，member=Unix 纳秒 | 清旧成员 + `ZADD` + `ZCARD` | 每次请求设 2m | 滑动 60 秒窗口；过期只负责回收 Key |
| 文章反馈去重 | `help_center:feedback:<articleID>:<clientIP>` | 字符串 `1` | `SET NX` | 24h | DB 写失败时尝试 `DEL`，允许重试 |
| 页面访问 | `page_visits:<contactID>` | 最多 20 个 JSON 字符串，最新在头部 | `LPUSH/LTRIM/LRANGE` | 每次写刷新 24h | 相邻同 URL 尽力去重；自然过期 |
| Inbox OAuth | `inbox_oauth:<state>` | Hash：provider、redirect URI、client ID、client secret、flow type、inbox ID、可选 tenant ID | `HSET` / `HGETALL` | 15m | Callback 读后尝试 `DEL` |
| OTP pending | `ai:otp:pending:<conversationUUID>` | JSON：code、规范化 email、attempts | `SET` / Lua `GET` | 10m | 正确、达到 3 次错误、损坏时删除；普通错误用 `KEEPTTL` |
| OTP verified | `ai:otp:verified:<conversationUUID>` | 已证明所有权的规范化 email | Lua `SET EX` / `GET` | 30m | email 变化前与 pending 一并删除 |
| OTP 发送次数 | `ai:otp:sends:<conversationUUID>:<email>` 与 `ai:otp:sends:<conversationUUID>` | 十进制计数器 | Lua `INCR` / `MGET` | 首次递增时设置 30m | 分别限制单地址 3 次、单会话 6 次 |

后台 Session 与 Help Center Cache 的最终 Key 结构不是从命名推测：分别来自上述锁定版本 `simplesessions` Redis Store 的 `defaultPrefix="session:"`、`defaultSessKey="_ss"`，以及 `goredis.Store.key/field` 的拼接实现。

---

## 6. 核心链路一：Session 如何创建、读取与失效

### 6.1 从登录写入到请求恢复身份

源码入口：[`Auth.SaveSession`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:259:1) → [`Auth.ValidateSession`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:342:1) → [`generateSessionToken`](vscode://file/D:/codes/dev_proj/libredesk/cmd/chat.go:954:1) / [`loadSession`](vscode://file/D:/codes/dev_proj/libredesk/cmd/chat.go:980:1)。

#### 为什么 Session 要放到 Redis

存在两套独立 Session：

- 后台 Agent Session：浏览器 Cookie 只保存随机 Session ID，用户快照在 Redis；API Key（接口密钥）认证不经过它。
- Widget Session：前端持有 Bearer token，Redis Hash 把 token 映射到 Contact/Visitor、Inbox 和 external user 身份。

两者都需要后续请求乃至不同进程实例能读取，因此状态放在 Redis，而不是当前进程 map。

#### 从登录写入到请求恢复身份

后台密码登录：

```text
cmd/handlers.go:initHandlers
  -> rateLimit(handleLogin, "auth")
  -> cmd/login.go:handleLogin
  -> user.Manager.VerifyPassword (DB)
  -> auth.Auth.SaveSession
  -> simplesessions.Manager.NewSession
  -> Redis Store.Create
  -> Session.SetMulti
  -> Redis Store.SetMulti
  -> response Set-Cookie: libredesk_session=<id>
```

后台请求验证：

```text
auth/perm middleware
  -> authenticateUser
  -> Auth.ValidateSession
  -> Manager.Acquire (读 Cookie)
  -> Session.GetMulti
  -> Redis HMGET session:<id> _ss id email first_name last_name
  -> user.Manager.GetAgentCachedOrLoad
  -> handler
```

OIDC（OpenID Connect，开放身份连接）登录先由 `handleOIDCLogin -> SetSessionValues` 在自动创建的临时 Session 中保存 state/next；Callback 经 `GetSessionValue` 校验 state 后，`SaveSession` 新建正式 Session。

Widget 新访客：

```text
handleChatInit
  -> createVisitorContact
  -> user.Manager.CreateVisitor (DB)
  -> generateSessionToken
  -> Redis Pipeline(HSET widget_session:<token>, EXPIRE)
  -> token 返回浏览器
```

Widget 已验证 Contact：

```text
handleAuthExchange
  -> 校验 JWT（JSON Web Token）并 resolve/create Contact
  -> GET widget_user:<inbox>:<contact>
  -> loadSession(oldToken)
     -> HGETALL widget_session:<token>
     -> EXPIRE 滑动续期
  -> 有效则复用；否则 generateSessionToken
  -> SET 反向索引并返回 token
```

后续 HTTP 是 `widgetAuth -> loadSession -> 校验 inbox -> DB 校验 user 存在且 enabled`；WebSocket join 是 `handleInboxJoin -> loadSession -> 校验 inbox -> DB 校验 user`。

#### Session Key、Cookie 与用户字段

后台核心是 `internal/auth.Auth`，持有 `*simplesessions.Manager` 与 `*redis.Client`。LibreDesk 写入的正式用户字段是 `internal/auth/models.User` 的 `ID/Email/FirstName/LastName`。Redis Hash 还带依赖用于判定 Key 存在的 `_ss=1`。

Widget 核心是 `cmd/chat.go:WidgetSession`：

```text
UserID int
InboxID int
IsVisitor bool
ExternalUserID string
```

token 使用 `crypto/rand` 生成 32 字节，再做无 padding 的 Base64 URL 编码；token 本身不携带可解码身份。

#### 创建、读取、过期与注销

后台必须满足：Cookie ID 对应的 Redis Hash 存在，Hash 中 `id > 0`，随后 DB/进程缓存读到的 Agent 仍存在且 enabled。Session 中的姓名与邮箱只是快照；权限和 enabled 状态由 `GetAgentCachedOrLoad` 得到的当前用户对象决定。

Widget 必须满足：token Hash 存在、`session.InboxID == 当前 Inbox.ID`、用户在 DB 中存在且 enabled。合并 Visitor 到 Contact 时还检查两个 Session 属于同一 Inbox、旧 Session 确实为 Visitor、两者 UserID 不同；DB 合并成功后才删除 Visitor token。

【代码分析】Widget token 是服务器端可撤销 opaque token（不透明令牌）；后台 Session 也是服务器端状态 Session。它们的权限判断不只信任 Redis 中的用户 ID，而会继续访问 DB/用户缓存，这是关键边界。

#### 并发请求与 Redis 故障窗口

后台 TTL 是固定生命周期：`Auth.New` 调用 `SetTTL(lifetime, false)`。依赖 Store 只在 `Create` 时 `EXPIRE`，`Get/GetMulti/SetMulti` 均不会续期。因此 `ValidateSession`、OIDC 临时字段写入、普通请求都不会滑动刷新。

`SaveSession` 不是一个 Redis 原子动作：`NewSession` 先用 `TxPipeline` 创建 `_ss` 并设 TTL、再写响应 Cookie，LibreDesk 随后才 `SetMulti` 用户字段。若最后一步失败，可能留下只含 `_ss` 的空会话直到 TTL；调用者得到错误，登录响应失败。

`Auth.New` 设置了 `EnableAutoCreate=true`。锁定版本 `Manager.Acquire` 在请求没有 Session Cookie 时会直接 `NewSession`，而 `ValidateSession` 随后对这个只含 `_ss` 的 Session 做 `GetMulti`，得到空用户字段；LibreDesk 最终以 `ID<=0` 拒绝认证。这意味着没有 Cookie 的 GET 请求只要进入 `auth/perm/authPage/notAuthPage` 的 Session 分支，就可能先创建一个 9h 空 Redis Session 并写响应 Cookie；它不是“只在成功登录后才创建 Session”。

后台 logout 是 `handleLogout -> Auth.DestroySession -> Session.Destroy`。锁定版本依赖先 `DEL session:<id>`，成功后才写过期 Cookie。Redis 删除失败时 handler 返回通用错误，Cookie 不会在该调用中被清掉。

Widget 的 `HSET+EXPIRE` 使用普通 `Pipeline`，不是 `TxPipeline` 或 Lua；正向 Session 与 `widget_user` 反向索引也分两次写。`loadSession` 读取成功以后调用 `Expire`，但没有检查结果；所以续期失败不会使当前请求失效。`deleteSessionToken` 和反向索引 `Set` 的错误也未检查。

【代码分析】Contact auth exchange 可能出现“正向 token 已创建但反向索引未成功”，或“反向索引指向已过期/写失败 token”。代码会在下一次 exchange 尝试读旧 token，校验失败后再创建新 token，属于可恢复但会遗留临时不一致的设计。

#### 共享 Session 的收益与边界

能够证明的是：后台把 Cookie 设置为 `HttpOnly`、按配置设置 `Secure`、`SameSite=Lax`；Widget 需要 Visitor/Contact 两种长期身份并支持配置化 Contact 生命周期；两者都在每次认证后再校验当前用户。

【合理推断】后台固定 9h 更接近安全边界明确的工作台登录；Widget 180d 与滑动续期更接近长期访客识别。源码没有作者设计说明，因此这只是从实际生命周期差异得到的推断，不是作者意图事实。

### 面试表达

> 后台 Session 把登录身份存进 Redis，并用 Cookie 只携带 Session 标识；请求到来时再从 Redis 恢复用户。TTL 决定最长生命期，是否滑动续期则要看读取路径是否刷新过期时间。

## 7. 核心链路二：Help Center 旁路缓存与失效

### 7.1 从缓存命中到写后失效

源码入口：[`helpCenterCacheOpts`](vscode://file/D:/codes/dev_proj/libredesk/cmd/helpcenter.go:78:1) → [`cachedHCPage` 的实际包装点](vscode://file/D:/codes/dev_proj/libredesk/cmd/helpcenter.go:1144:1) → [`initFastCache`](vscode://file/D:/codes/dev_proj/libredesk/cmd/init.go:945:1)。

#### 为什么页面响应适合旁路缓存

`cacheHCPage` 缓存公开 Help Center 的首页、搜索页、Collection 页、Article HTML/Markdown 的完整 200 响应 body、Content-Type 和 ETag（实体标签，用于 HTTP 条件请求）。普通 CRUD、浏览器静态资源缓存不属于这个 Redis Cache 深入对象。

#### 从缓存命中到未命中回填

```text
cmd/handlers.go public GET/HEAD route
  -> rateLimit(..., "public")
  -> cachedHCPage / cachedHCNoIndexPage
  -> cacheHCPage
  -> app.fc.Cached(rendered, options, "helpcenter")
     -> goredis.Store.Get
     -> HIT: 回放 body/content-type，或 ETag 命中返回 304
     -> MISS/Redis error: 执行真实 handler -> DB 查询/模板渲染
     -> 仅 status=200 且无 Cache-Control:no-store 时 Store.Put
```

失效链：

```text
cmd/handlers.go 中会影响页面的管理写路由
  -> auth/perm
  -> clearsHCCache(realHandler)
  -> realHandler 完成 DB 写与响应
  -> response status < 300
  -> app.fc.DelGroup("hc", "helpcenter")
  -> DEL libredesk:cache:hc:helpcenter
```

#### Cache Key、Hash 与 ETag

`helpCenterCacheOpts` 选择 namespace=`hc`、group=`helpcenter`、TTL=30m、ETag=true、IncludeQueryString=true；`initFastCache` 选择 Redis Store prefix=`libredesk:cache:`。

最终只有一个分组 Hash Key：`libredesk:cache:hc:helpcenter`。URI 是完整 URI（包含 query string）的 MD5（消息摘要算法）十六进制；每个 URI 用四个 field 保存 content type、etag、compression、blob。LibreDesk 没启用 Store 的 Async，所以写入同步进入 Redis Pipeline。

#### 数据修改后的缓存失效

这是 cache-aside（旁路缓存）：读先查缓存，miss 后由 handler 查 DB/渲染，再缓存成功响应。Redis 不是页面事实源；DB/模板仍是事实源。

必须维持的不变量是：会改变公开页面内容的成功写操作之后，旧分组不能继续对外服务。当前实现通过 `clearsHCCache` 删除整个 group，而不是计算单 URI 依赖。

#### 并发读写与陈旧窗口

Cache 读错误仅写日志并执行真实 handler；Cache 写错误仅写日志，原 200 响应仍返回；失效错误也仅写日志，DB 写响应不回滚。因此 Redis Cache 是 fail-open 的性能层。

【代码分析】DB 更新与 Redis 删除不在同一事务：先完成 handler/DB 变化，后删 Cache。删除失败时，已提交的新 DB 状态与旧 Cache 并存，最长多久不能只说“30m”，原因见下一条。

TTL 挂在整个 group Hash，而不是每个 URI field。任何一个 miss 写入都会对整个 Hash 再执行 `PEXPIRE 30m`。因此一个旧 field 的实际寿命可能被其他 URI 的持续 miss/写入反复延长；“每条页面最多陈旧 30m”并不是该 Store 能保证的不变量。

【合理推断】存在经典的回填竞态：读请求先 miss 并从旧 DB 快照渲染；写请求提交并删 group；读请求随后把旧页面写回新 group。该风险可由调用顺序推导，但是否在生产负载发生需要实验。

#### 共享缓存的收益与边界

源码显示多种变化都会清整个组，包括 Help Center/Collection/Article、General Settings、Agent 头像/资料、AI Assistant；这说明一个页面依赖多个实体，当前实现选择粗粒度失效。`IncludeQueryString=true` 又保证不同 locale/query/Markdown URL 不互相覆盖。

【代码分析】全组删除降低了依赖追踪复杂度，代价是任意管理写会让所有页面 miss。Redis 后端使多个服务实例共享命中与失效结果；这是从数据放置和调用效果得到的分析，不是假装知道作者意图。
### 文章反馈去重不是响应 Cache

`handleHelpCenterArticleFeedback` 在 DB 插入前执行 `SET NX help_center:feedback:<article>:<IP> 1 EX 24h`。Key 已存在就直接返回成功，不重复写 DB；Redis 报错则继续 `RecordArticleFeedback`，所以去重故障时选择保留反馈、接受潜在重复。DB 插入失败会尝试删除去重 Key，使用户可重试。

【代码分析】它解决的是业务去重而非读取加速。原子性只覆盖“抢占去重 Key”，不覆盖 Redis 与 PostgreSQL 的整体提交；进程崩溃于 SETNX 成功、DB 写入之前，会在 24h 内吞掉该 IP 的重试。

---

### 面试表达

> Help Center 使用旁路缓存：读未命中回源数据库，写路径改完数据库后失效缓存。DB 成功而缓存删除失败会留下陈旧读窗口，因此缓存不是新的事实源。

## 8. 核心链路三：Redis 滑动窗口限流

### 8.1 从请求计数到窗口内拒绝

源码入口：[`rateLimit` 中间件](vscode://file/D:/codes/dev_proj/libredesk/cmd/middlewares.go:242:1) → [`Limiter.Check`](vscode://file/D:/codes/dev_proj/libredesk/internal/ratelimit/ratelimit.go:40:1)。

#### 为什么限流计数需要跨实例共享

对公开/未认证入口按来源 IP 限制每分钟请求数，规则分 `widget/auth/public/media`。默认 RPM（Requests Per Minute，每分钟请求数）分别为 100/30/100/300，可在 `[rate_limit.<name>]` 禁用或覆盖正数阈值。

#### 从路由中间件到 `Limiter.Check`

主要链路是 `initHandlers -> rateLimit(handler, rule) -> Limiter.Check -> handler`。`authOrSignedURL` 只对最终走 public media 的请求调用 `media` 规则，正常 Session/API Key 认证成功则不收费。Help Center 自定义域在 router NotFound 重写之前也会直接调用 `Check("public")`，并用 `rateLimitPaidKey` 防止重写后路由二次收费。

#### 滑动窗口所用的 Redis 命令

`ratelimit.Rule{Name, Enabled, RequestsPerMinute}` 存在 `Limiter.rules` 进程内 map；计数状态在 Redis：

```text
key = rate_limit:<ruleName>:<realip.FromRequest(ctx)>
ZREMRANGEBYSCORE key -inf nowUnix-60
ZADD key score=nowUnix member=nowUnixNano
ZCARD key
EXPIRE key 120s
```

超过阈值返回 429，并写 `X-RateLimit-*`、`Retry-After: 60`；未超过时写 remaining。

#### 计数、拒绝与过期语义

当前请求先加入 ZSet，再计数，因此被拒绝的请求也进入窗口。窗口维度只有“规则名 + IP”，没有 User、API Key、具体 Resource ID；同 IP 下同一规则的不同端点共用额度。

【代码分析】Redis 使所有 LibreDesk 实例对同一个 IP/rule 聚合计数；若改成进程 map，多实例会把可用额度近似放大为“阈值 × 实例数”。

#### Pipeline 交错与失败传播

四条命令使用普通 `Pipeline`，并未使用 `TxPipeline`、Lua 或其他原子结构。

`go-redis` 明确区分 `Pipeline` 与会包装 `MULTI/EXEC` 的 `TxPipeline`。因此当前四命令是一次批量往返优化，但没有事务原子性保证。并发请求可能在 cleanup/add/count 之间交错；不能把它描述成“原子滑动窗口”。

`pipe.Exec` 只要报错，`Check` 直接 `return nil`：请求被放行、没有限流响应头。这是明确的 fail-open，而不是推断。

#### 关键代码：限流存储失败时选择放行

```go
pipe.ZRemRangeByScore(ctx, key, "-inf", windowStart)
pipe.ZAdd(ctx, key, redis.Z{Score: float64(nowUnix), Member: nowNano})
countCmd := pipe.ZCard(ctx, key)
pipe.Expire(ctx, key, 2*time.Minute)
if _, err := pipe.Exec(ctx); err != nil {
    return nil
}
```

**这段代码解决什么问题：** 四个 Redis 命令批量发送，减少一次请求中的网络往返；Redis 故障时公开 API 不因限流依赖而整体不可用。

**为什么这样写：** Pipeline（流水线）优化往返，`return nil` 明确采用 Fail-open（故障放行）策略。

**如果没有这段机制会怎样：** 若错误向上传播并拒绝请求，Redis 短暂故障会放大为所有受限入口不可用。

**当前工程代价：** 故障期间保护能力消失；普通 Pipeline 也不提供四条命令的事务原子性，并发边界只能通过实验量化。

【代码分析】`X-RateLimit-Reset=now+60` 不是根据最老成员计算的精确可用时间，而是当前时刻加 60 秒。它是保守提示，不是窗口精确重置点。

#### 共享限流的收益与边界

配置注释明确称其为 unauthenticated endpoints 的 per-IP rate limits；路由实际也优先覆盖 Widget、登录、公共 Help Center/CSAT 和 public media。WebSocket upgrade 受 Redis 规则限制，但连接建立后的 frame 由 `safeConn.allow` 在内存中按连接限制。

【代码分析】按规则聚合比每 Resource 建 Key 简单，普通 Pipeline 降低网络往返；代价是并发边界不严格、同 NAT（网络地址转换）出口用户共享额度。源码没有作者权衡说明，后一句属于分析。

### 面试表达

> 限流把共享窗口状态放在 Redis，使多实例看到同一计数。Pipeline 只减少网络往返，不自动提供事务原子性；是否会在 cleanup、add、count 间交错必须按具体命令判断。

## 9. 跨链路比较：Redis 与进程内存

| 状态 | 实际存放 | 为什么当前设计需要/不需要跨请求与跨实例共享 |
|---|---|---|
| 后台/Widget Session | Redis | 任一实例都要用客户端 token 还原身份；logout/过期需对所有实例生效 |
| HTTP 限流计数 | Redis | 同 IP 的额度必须跨实例聚合，否则每实例各算一份 |
| Help Center 响应 | Redis | 多实例共享命中；一次管理写的全组失效能影响所有实例 |
| OTP、OAuth state、反馈去重 | Redis | 后续 callback/工具调用可能落到不同实例；安全状态与一次性状态不能绑定某进程 |
| Widget page visits | Redis | Agent 查看与 Widget 写入是不同请求，也可能落不同实例 |
| `user.Manager.agentCache` | 进程内 `map[int]cachedAgent` + `RWMutex` | 只是 DB 用户读取加速；miss 可回 DB，10m TTL 限制陈旧时间，不承担跨实例协议 |
| `aiagent.Manager` 的 queue/inflight/pending/assistantUserIDs | 进程内 channel/map + Mutex | Worker 协调当前进程；它们不是 Redis Cache，也没有跨实例共享语义 |
| `safeConn.lastAt` | 每 WebSocket 连接内 map + Mutex | 一个连接由一个进程持有，frame 节流只需该连接局部状态 |

Agent Cache 的 `GetAgentCachedOrLoad` 是 cache-aside：命中返回，miss 调 `GetAgent -> DB` 并写入 10m TTL；多条用户、角色、团队变更路径调用 `InvalidateAgentCache/InvalidateAllAgentCache`。

【代码分析】Agent Cache 的失效只清当前实例，因此多实例中其他进程可能继续使用旧用户对象直到 10m TTL。这与 Redis Help Center Cache 的共享失效不同。是否会造成可观察的权限/disabled 延迟，需要多实例实验确认；不能仅凭“map”就断言已发生安全事故。

【代码分析】“必须跨实例”不是说 Redis 数据都必须持久化。Session/OTP/OAuth/limit 的共同点是协议下一步可能落到任意实例，且多个实例必须看到同一状态；`safeConn` 和 Worker inflight 则只描述当前进程拥有的资源，跨实例共享反而会改变其职责。

---

### 9.1 Redis 故障如何传播

| 功能 | timeout / unavailable 后源码行为 | 请求/服务结果 |
|---|---|---|
| 服务启动 | `initRedis` 不 `PING` | 单凭源码不能证明启动失败；首次命令才暴露故障 |
| 后台 login/OIDC Session 创建 | `SaveSession/SetSessionValues/GetSessionValue` 返回错误 | 密码登录返回通用错误；OIDC 流转为登录错误 |
| 后台受保护 API | `ValidateSession` 错误被认证层折叠为无效/过期 Session | 通常 401；不会回退 DB 生成无状态登录 |
| 后台 logout | `DestroySession` 返回错误 | logout 返回通用错误；依赖不会继续清 Cookie |
| Widget Session 创建 | Pipeline 错误上传 | Visitor/init 或 auth exchange 失败 |
| Widget Session validate | `HGETALL` 错误上传给 `loadSession` | HTTP 401；WS join 失败 |
| Widget Session refresh/delete/reverse Set | 错误未检查 | 当前成功路径继续，但可能未续期/未删除/未建反向索引 |
| Help Center Cache read/write | fastcache 记录日志 | 读回源 DB；写失败仍返回真实响应 |
| Help Center Cache invalidate | `clearsHCCache` 记录日志 | DB 更新仍成功，旧缓存可能继续服务 |
| Rate Limit | `Exec` 错误后 `return nil` | fail-open，请求继续 |
| 文章反馈去重 | `SETNX` 错误不阻止 DB 写 | 反馈保留，可能重复 |
| Page visits | Redis 读/写错误返回空或停止广播 | 核心对话继续，页面上下文缺失 |
| Inbox OAuth state | HSET/EXPIRE/HGETALL 错误上传 | authorize/callback 失败 |
| OTP verified read | 非 `redis.Nil` 记录错误并返回 false | fail-closed：视为未验证 |
| OTP pending/check/cap | 错误上传给 AI Tool | 当前 Tool 调用失败 |
| OTP send counter after邮件已发 | 错误只记日志 | 邮件已成功仍向上返回成功，但次数可能未完整记录 |

### 两个关键的非统一故障窗口

Inbox OAuth 先 `HSET` 再单独 `EXPIRE`。如果 HSET 成功而 EXPIRE 失败，handler 返回错误，但 Key 可能无 TTL，且 Value 包含 `client_secret`。Callback 的 `HGETALL` 和 `DEL` 也不是原子 consume，`DEL` 错误被忽略。

【代码分析】因此它值得优先做故障注入：确认“写成功、设 TTL 失败”和两个并发 callback 是否会留下敏感状态或重复消费。这不是 Redis Cluster 等横向扩展话题，而是当前两条命令顺序直接形成的生命周期问题。

OTP 的正确校验与 pending→verified 转换由 Lua 一次执行，具备 Redis 内的原子转换；但两个发送计数器分别运行脚本。如果第一个成功、第二个失败，会出现部分计数。邮件发送成功后，计数失败只记录日志，不让 Tool 失败。

---

## 10. 已确认的工程限制与待实验验证

- Session、Cache 与限流共用 Redis，但状态价值、TTL 和失败策略不同。
- Redis Key 的结构与续期行为必须沿真实 Store 和调用路径确认。
- Pipeline 是批量传输机制，不能直接当作原子事务。

| 实验问题 | 为什么需要实验 | 最小验证方法 | 成功 / 失败分别说明什么 |
|---|---|---|---|
| Widget Session 续期失败 | `loadSession` 忽略 `EXPIRE` error | 让 `HGETALL` 成功、`EXPIRE` 失败，比较调用前后 TTL | Session 仍返回说明故障被降级；请求失败则与当前代码分析冲突 |
| Help Center 回填竞态 | 旧 DB 快照可能在写后失效之后重新回填 | Reader 读旧值后暂停，Writer 提交并删组，再恢复 Reader Put | 最终旧 body 命中确认陈旧回填窗口；新值说明底层另有保护 |
| 限流 Pipeline 并发 | 普通 Pipeline 不提供事务原子性 | 多 goroutine 同 IP、阈值 10，统计放行数与 `ZCARD` | 超额放行量化交错窗口；严格 10 只能证明该轮未触发竞态 |
| Redis 故障放行 | 限流错误路径直接 `return nil` | 关闭 Redis 后请求受限路由 | Handler 继续执行确认 Fail-open；被拒绝说明还有其他边界 |
| OAuth 临时状态 TTL | `HSET` 与 `EXPIRE` 分离 | 注入 `HSET` 成功、`EXPIRE` 失败 | 无 TTL Key 证明敏感临时状态窗口；自动清理说明底层有额外机制 |

## 11. 面试表达

> LibreDesk 共用 Redis，但 Session、Cache 和 Rate Limit 的语义不同。Session 保存跨请求身份并依靠 TTL 失效；Help Center 采用可重建缓存，读未命中回源 DB，写后需要失效；限流则把共享计数放在 Redis，使多个应用实例看到同一窗口状态。判断一致性时必须逐条看 Key、TTL 和失败传播，不能因为都使用 Redis 就认为可靠性相同。

## 本章必须记住的源码锚点

### [`SaveSession`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:259:1)
**为什么必须记住：** Agent Session 的 Redis 写入与 Cookie 建立点。  
**面试关联：** 为什么 Session 是 Redis 中的共享状态？

### [`ValidateSession`](vscode://file/D:/codes/dev_proj/libredesk/internal/auth/auth.go:342:1)
**为什么必须记住：** 请求身份恢复与 Session TTL 语义。  
**面试关联：** 固定过期和滑动过期如何从源码区分？

### [`generateSessionToken`](vscode://file/D:/codes/dev_proj/libredesk/cmd/chat.go:954:1)
**为什么必须记住：** Widget Token、Hash 与反向索引的生命周期入口。  
**面试关联：** 删除一个 Widget Session 为什么涉及多个 Key？

### [`cacheHCPage`](vscode://file/D:/codes/dev_proj/libredesk/cmd/helpcenter.go:1135:1)
**为什么必须记住：** Help Center 旁路缓存的读取与回填。  
**面试关联：** Redis 缓存失败为何可以回源 DB？

### [`clearsHCCache`](vscode://file/D:/codes/dev_proj/libredesk/cmd/helpcenter.go:1171:1)
**为什么必须记住：** 管理写入后以分组删除实现失效。  
**面试关联：** 粗粒度失效的简单性与缓存抖动如何权衡？

### [`Limiter.Check`](vscode://file/D:/codes/dev_proj/libredesk/internal/ratelimit/ratelimit.go:40:1)
**为什么必须记住：** Redis Sorted Set 限流与 fail-open 策略。  
**面试关联：** Redis 故障时为什么是放行而不是拒绝？

## 12. 面试追问

1. 后台 Session 与 Widget Session 为什么是两套模型？
2. 如何从读路径判断 Session 是否滑动续期？
3. DB 更新成功但缓存删除失败会怎样？
4. Redis Pipeline（流水线）为什么不天然等于原子事务？
5. Redis 不可用时，Session、Cache 与限流应分别失败开放还是失败关闭？
