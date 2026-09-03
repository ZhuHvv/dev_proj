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

[server/worker 进程入口](../../app/worker.py#L33) → [build_container()](../../app/composition.py#L129) → Settings → 仓库/外部客户端 → [MainAgentFactory](../../app/application/agents/main_agent.py#L59) → [MainAgentOrchestrator.handle_intent](../../app/application/agents/orchestrator.py#L140) → [build_app()](../../app/presentation/server.py#L54)。组装根位于 [composition.py](../../app/composition.py)，API 与 worker 共用同一套业务组装。

## 请求主链

[React App](../../frontend/src/App.tsx#L22) → [POST intent](../../app/presentation/server.py#L131) → 直跑或 [Redis Stream 消费](../../app/infrastructure/queue/redis_stream_queue.py#L101) → [Orchestrator](../../app/application/agents/orchestrator.py#L140) → MainAgent → 工具/子 Agent → [CatalogSearchUseCase](../../app/application/usecases/catalog_search.py#L104) 等 UseCase → Domain/Infrastructure → [EventBus](../../app/infrastructure/eventbus.py#L107) → WebSocket。

## 数据与副作用

默认开发形态使用种子商品、SQLite 状态与可选 Redis/Qdrant；订单和偏好会写存储，事件可持久化，模型/向量/精排是外部调用。

## 教程与当前实现的关系

教程中的初始化步骤可能随版本变化；依赖和启动参数以 [pyproject.toml](../../pyproject.toml)、[README.md](../../README.md)、[settings.py](../../app/infrastructure/settings.py) 与 [docker-compose.yaml](../../docker/docker-compose.yaml) 为准。
