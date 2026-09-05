# 09 Globex项目总览与工程初始化

> [钉钉原文](https://docs.dingtalk.com/i/nodes/GZLxjv9VGqgwQMXxt6BgjX6x86EDybno) · 当前结论：**已落地**。

## 目录与职责

| 目录 | 责任 |
| --- | --- |
| `app/domain/` | 商品、订单、运费等核心模型与端口 |
| `app/application/` | Agent、工具、UseCase、Prompt、Harness |
| `app/infrastructure/` | 模型、缓存、队列、数据库、向量库、观测实现 |
| `app/presentation/` | FastAPI 与 WebSocket 入口 |
| `frontend/` | React 交互界面 |
| `tests/`、`scripts/`、`eval/` | 自动测试、验证和评测 |

## 启动主链

API 启动：[模块末尾 app = build_app()](D:/codes/dev_proj/globex-agent/app/presentation/server.py:291) → 注册 FastAPI 路由和 lifespan → lifespan 启动时 build_container() → 创建 ConnectionManager → Container.startup() → 等待请求。收到意图后才调用 handle_intent；MainAgent 由 SessionRegistry 按需创建。worker 另从 [main()](D:/codes/dev_proj/globex-agent/app/worker.py:33) 进入 build_container() → startup() → consume()。组装函数、启动函数和请求处理函数不是一条连续的调用顺序。

## 请求主链

[React App](../../frontend/src/App.tsx#L22) → [POST intent](../../app/presentation/server.py#L131) → 直跑或 [Redis Stream 消费](../../app/infrastructure/queue/redis_stream_queue.py#L101) → [Orchestrator](../../app/application/agents/orchestrator.py#L140) → MainAgent → 工具/子 Agent → [CatalogSearchUseCase](../../app/application/usecases/catalog_search.py#L104) 等 UseCase → Domain/Infrastructure → [EventBus](../../app/infrastructure/eventbus.py#L107) → WebSocket。

## 数据与副作用

默认开发形态使用种子商品、SQLite 状态与可选 Redis/Qdrant；订单和偏好会写存储，事件可持久化，模型/向量/精排是外部调用。

## 教程与当前实现的关系

教程中的初始化步骤可能随版本变化；依赖和启动参数以 [pyproject.toml](../../pyproject.toml)、[README.md](../../README.md)、[settings.py](../../app/infrastructure/settings.py) 与 [docker-compose.yaml](../../docker/docker-compose.yaml) 为准。
