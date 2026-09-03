# 16-1 Docker Compose 全栈编排与环境锁定

> [钉钉原文](https://docs.dingtalk.com/i/nodes/Exel2BLV5zwPpkRjhP2DLjO1Jgk9rpMq) · 当前结论：**已落地**。

## 当前编排

[docker-compose.yaml](../../docker/docker-compose.yaml) 定义 app、worker、Redis、Qdrant 与 frontend；[Dockerfile](../../Dockerfile) 构建 Python 服务；[uv.lock](../../uv.lock) 锁定 Python 依赖。

## 启动关系

[Compose 服务编排](../../docker/docker-compose.yaml#L11) → Redis/Qdrant 健康 → app 与 [worker.main](../../app/worker.py#L33) 读取同一环境配置 → [app 提供 HTTP/WS](../../app/presentation/server.py#L54) → [worker 消费 Redis Stream](../../app/infrastructure/queue/redis_stream_queue.py#L101) → [frontend 连接 app](../../frontend/src/App.tsx#L34)。API 与 worker 都从 [build_container](../../app/composition.py#L129) 构造相同领域与基础设施依赖。

## 持久化与副作用

Redis 保存队列、任务状态、缓存和可选共享熔断；Qdrant 保存向量；SQLite/卷保存 session、订单、偏好和对话。删除卷会丢开发数据，升级模型/向量维度时需要显式重建索引。

## 环境锁定边界

`uv.lock` 锁 Python 包，但模型服务、外部 API 和种子数据仍可能漂移；前端还有自己的包锁。Compose 是本地/单机集成环境，不等于生产高可用部署。

## 验证重点

除“容器起来”外，还应验证 health、app 到 Redis/Qdrant 的网络、worker 消费、WS 推送和卷重启后的状态恢复。
